"""Admin review-queue routes.

GET  /admin/submissions/pending    list pending submissions, oldest first
POST /admin/submissions/{id}/approve
POST /admin/submissions/{id}/approve-and-publish-osm   (optional ?picker_choice=)
POST /admin/submissions/{id}/return  (form field: note, optional)

GET  /admin/osm/connect           redirect to OSM authorize URL
GET  /admin/osm/callback          exchange code → store tokens
GET  /admin/osm/status            JSON {connected, username, today_count, cap, dry_run}
POST /admin/osm/disconnect        clear stored credentials

Each pending row carries enough context for the reviewer to decide without
clicking through: photo URL, name, category, description, submitter callsign,
coords + an OpenStreetMap URL (so the reviewer can check if the POI exists
upstream), and submitted_at. The photo and card endpoints already exist
under /submissions/{id}/photo.jpg + /submissions/{id}/card.jpg.

All routes here 404 for non-admins via the require_admin dep.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from geoalchemy2 import Geometry
from pydantic import BaseModel
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.admin.deps import require_admin
from dispatchzero.config import Settings, get_settings
from dispatchzero.db import get_session
from dispatchzero.models import Place, Submission, SubmissionStatus, User
from dispatchzero.services import (
    osm_candidates,
    osm_oauth,
    osm_publish,
    osm_tagging,
)
from dispatchzero.services.submissions import (
    SubmissionNotFoundError,
    approve_submission,
    reject_submission,
)

# Cookie name for the OAuth state CSRF token. Set on the redirect to OSM,
# verified on the callback. Short-lived (10 min — same as the signed token's
# max_age).
_OSM_STATE_COOKIE = "dz_osm_state"

router = APIRouter(prefix="/admin", tags=["admin"])


class PendingSubmissionOut(BaseModel):
    id: uuid.UUID
    name: str
    category: str | None
    description: str | None
    # User-provided URL (Wikipedia, official site, etc.) shown as a
    # clickable line on the queue card. Used at publish time to derive
    # the wikipedia= or website= tag on OSM.
    external_link: str | None = None
    submitter_callsign: str
    submitter_style: str
    submitted_at: str
    lat: float
    lng: float
    maps_url: str
    photo_url: str
    card_url: str
    # OSM publishability — drives whether the admin UI shows the
    # Approve+OSM button and whether it renders the subtype picker.
    # `osm_publishable=False` means no tag mapping exists at all (we
    # never publish this category); the button is hidden. `osm_picker`
    # is non-null when the category is ambiguous (historic/infrastructure)
    # and the reviewer must pick a subtype before publishing.
    osm_publishable: bool = False
    osm_picker: list[dict] | None = None
    # Defense-in-depth dedup: backend says whether this place has already
    # been pushed to OSM (places.osm_published_node_id). The UI hides the
    # Submit-to-OSM button when true. publish_submission_to_osm also
    # re-checks this server-side before any HTTP work.
    osm_already_published_node_id: int | None = None


class SubmissionActionOut(BaseModel):
    id: uuid.UUID
    status: str


class OsmStatusOut(BaseModel):
    """GET /admin/osm/status — what the admin UI needs to render the
    OSM banner + gate the Approve+OSM button."""
    connected: bool
    username: str | None = None
    today_count: int
    daily_cap: int
    dry_run: bool
    # Surface whether OAuth creds are even configured on the server.
    # When false, the Connect button is disabled with a hint.
    server_configured: bool


class OsmPublishOut(BaseModel):
    """POST /admin/submissions/{id}/approve-and-publish-osm response.
    Carries the submission action result PLUS the OSM-side IDs (or
    nulls in dry-run mode) so the UI can show a "published as node X"
    badge or a dry-run notice."""
    id: uuid.UUID
    status: str
    osm_changeset_id: int | None = None
    osm_node_id: int | None = None
    osm_dry_run: bool
    osm_tags: dict[str, str]


@router.get(
    "/submissions/pending",
    response_model=list[PendingSubmissionOut],
)
async def list_pending(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[PendingSubmissionOut]:
    """Return all pending submissions oldest-first so the reviewer works
    a FIFO queue rather than always seeing the newest noise.

    Coordinates are unpacked via ST_Y/ST_X on the geometry cast — the same
    pattern services/mission_flow.py uses. (We tried geoalchemy2's
    to_shape() first but it returned the WKB raw on Geography columns,
    silently dropping rows.)"""
    # ST_Y/ST_X need a geometry input; coordinates is Geography(POINT). Cast
    # via SQLAlchemy's cast() with the geoalchemy2 Geometry type so the cast
    # is a proper typed expression rather than a string literal.
    lat_col = func.ST_Y(cast(Place.coordinates, Geometry))
    lng_col = func.ST_X(cast(Place.coordinates, Geometry))
    rows = (
        await db.execute(
            select(
                Submission,
                Place,
                User,
                lat_col.label("lat"),
                lng_col.label("lng"),
            )
            .join(Place, Place.id == Submission.place_id)
            .join(User, User.id == Submission.user_id)
            .where(Submission.status == SubmissionStatus.PENDING.value)
            .order_by(Submission.submitted_at.asc())
        )
    ).all()

    out: list[PendingSubmissionOut] = []
    for submission, place, submitter, lat, lng in rows:
        # OSM publishability: simple categories publish straight through;
        # ambiguous ones (historic/infrastructure) require a subtype pick;
        # unknown categories aren't publishable at all.
        picker = osm_tagging.picker_choices(place.category)
        publishable = (
            picker is not None
            or osm_tagging.tags_for_publish(
                category=place.category,
                place_name=place.name or "",
            ) is not None
        )
        out.append(
            PendingSubmissionOut(
                id=submission.id,
                name=place.name or "",
                category=place.category,
                description=submission.description,
                external_link=submission.external_link,
                submitter_callsign=submitter.callsign,
                submitter_style=submitter.adventure_style,
                submitted_at=submission.submitted_at.isoformat(),
                lat=float(lat),
                lng=float(lng),
                # OSM map URL (not Google) so the reviewer can check whether
                # the submitted POI already exists upstream before approving.
                # mlat/mlon drops a marker; #map=ZOOM/LAT/LNG sets the view.
                # Zoom 19 is close enough to see individual buildings.
                maps_url=(
                    f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lng:.6f}"
                    f"#map=19/{lat:.6f}/{lng:.6f}"
                ),
                photo_url=f"/submissions/{submission.id}/photo.jpg",
                card_url=f"/submissions/{submission.id}/card.jpg",
                osm_publishable=publishable,
                osm_picker=picker,
                osm_already_published_node_id=place.osm_published_node_id,
            )
        )
    return out


@router.post(
    "/submissions/{submission_id}/approve",
    response_model=SubmissionActionOut,
)
async def approve(
    submission_id: uuid.UUID,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SubmissionActionOut:
    try:
        sub = await approve_submission(
            db=db, reviewer=admin, submission_id=submission_id,
        )
    except SubmissionNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return SubmissionActionOut(id=sub.id, status=sub.status)


@router.post(
    "/submissions/{submission_id}/return",
    response_model=SubmissionActionOut,
)
async def return_(
    submission_id: uuid.UUID,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
    note: Annotated[str | None, Form()] = None,
) -> SubmissionActionOut:
    try:
        sub = await reject_submission(
            db=db,
            reviewer=admin,
            submission_id=submission_id,
            note=note,
        )
    except SubmissionNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return SubmissionActionOut(id=sub.id, status=sub.status)


# ---------------------------------------------------------------------------
# OSM integration: OAuth connect flow + status + publish action.
# ---------------------------------------------------------------------------


@router.get("/osm/status", response_model=OsmStatusOut)
async def osm_status(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OsmStatusOut:
    """Snapshot of OSM connection state for the admin queue banner."""
    server_configured = bool(
        settings.osm_client_id and settings.osm_client_secret
    )
    creds = await osm_oauth.get_credentials(db)
    today_count = await osm_publish.todays_real_publish_count(db)
    return OsmStatusOut(
        connected=creds is not None,
        username=(creds.osm_username if creds else None),
        today_count=today_count,
        daily_cap=settings.osm_daily_publish_cap,
        dry_run=settings.osm_dry_run,
        server_configured=server_configured,
    )


@router.get("/osm/connect")
async def osm_connect(
    _admin: Annotated[User, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """Kick off OSM OAuth. Sets a short-lived signed cookie carrying the
    state token; OSM bounces back to /admin/osm/callback with the same
    state in the query string and the callback verifies they match."""
    if not (settings.osm_client_id and settings.osm_client_secret):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "OSM client credentials are not configured on the server.",
        )
    url, state = osm_oauth.build_authorize_url(settings)
    resp = RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    resp.set_cookie(
        key=_OSM_STATE_COOKIE,
        value=state,
        max_age=600,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/admin/osm",
    )
    return resp


@router.get("/osm/callback")
async def osm_callback(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    dz_osm_state: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    """OSM redirects here after the admin authorizes. Verifies state,
    swaps code for tokens, saves to osm_credentials, then bounces back
    to the admin queue with a flag the UI can read."""
    if error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"OSM returned error: {error}",
        )
    if not code or not state:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "missing code or state from OSM",
        )
    if not osm_oauth.verify_state(
        settings, cookie_state=dz_osm_state or "", query_state=state,
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "OAuth state mismatch — try Connect again",
        )
    try:
        token_response = await osm_oauth.exchange_code_for_tokens(
            settings, code=code,
        )
        await osm_oauth.save_credentials(
            db, settings, token_response=token_response,
        )
    except osm_oauth.OsmAuthError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e

    resp = RedirectResponse(
        url="/admin/queue?osm=connected",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    # Burn the state cookie so a replay can't re-trigger the callback.
    resp.delete_cookie(_OSM_STATE_COOKIE, path="/admin/osm")
    return resp


@router.post("/osm/disconnect", response_model=OsmStatusOut)
async def osm_disconnect(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OsmStatusOut:
    await osm_oauth.clear_credentials(db, settings)
    return await osm_status(_admin=_admin, db=db, settings=settings)


@router.post(
    "/submissions/{submission_id}/approve-and-publish-osm",
    response_model=OsmPublishOut,
)
async def approve_and_publish_osm(
    submission_id: uuid.UUID,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    picker_choice: Annotated[str | None, Form()] = None,
) -> OsmPublishOut:
    """Approve the submission AND publish a node to OSM in one shot.

    Order matters: we approve first (flipping the Place to ACTIVE) so a
    successful local-but-failed-OSM action still leaves the place
    dispatchable. If the OSM publish fails, the local approval stands
    and the error bubbles up — the admin can retry the OSM half later
    via a separate path (TODO if we ever need it; for now the simpler
    posture is "approve again or just leave it un-OSM'd").
    """
    # 1. Approve locally first.
    try:
        sub = await approve_submission(
            db=db, reviewer=admin, submission_id=submission_id,
        )
    except SubmissionNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e

    # 2. Reload the submission + place + coords for OSM publish.
    lat_col = func.ST_Y(cast(Place.coordinates, Geometry))
    lng_col = func.ST_X(cast(Place.coordinates, Geometry))
    row = (
        await db.execute(
            select(Submission, Place, lat_col, lng_col)
            .join(Place, Place.id == Submission.place_id)
            .where(Submission.id == submission_id)
        )
    ).one_or_none()
    if row is None:
        # Place gone? Shouldn't happen post-approve but defend anyway.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "submission approved but place is missing; cannot publish to OSM",
        )
    fresh_sub, place, lat, lng = row

    # 3. Publish (or dry-run).
    try:
        pub = await osm_publish.publish_submission_to_osm(
            db=db,
            settings=settings,
            submission=fresh_sub,
            place=place,
            lat=float(lat),
            lng=float(lng),
            reviewer=admin,
            picker_choice=picker_choice,
        )
    except osm_publish.OsmDailyCapReachedError as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e)) from e
    except osm_publish.OsmPublishError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    except osm_oauth.OsmAuthError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e

    return OsmPublishOut(
        id=sub.id,
        status=sub.status,
        osm_changeset_id=pub.changeset_id,
        osm_node_id=pub.node_id,
        osm_dry_run=pub.dry_run,
        osm_tags=dict(pub.tags_json),
    )


# ---------------------------------------------------------------------------
# Unified queue + completion-candidate actions (Phase 2).
#
# /admin/queue returns BOTH pending Submissions AND completion-driven OSM
# candidates as a mixed list, each tagged with a `kind` discriminator. The
# UI uses kind to render the right card layout + action set.
#
# Pure completion candidates have place-keyed actions (skip / publish-osm)
# since they don't have a submission to approve.
# ---------------------------------------------------------------------------


class OsmPreflightMatch(BaseModel):
    name: str
    osm_type: str
    osm_id: int
    osm_url: str
    distance_m: int
    tags_summary: str = ""


class OsmPreflightInfo(BaseModel):
    """State of the OSM pre-flight check for a queue item.

    `state` is one of:
      - "pending":  background check hasn't completed yet (or failed
                    silently — same surface, admin's clickable map link
                    is the fallback verification)
      - "clear":    check ran, found no nearby OSM matches at this
                    category — the place looks genuinely new
      - "matches":  check ran, found N nearby OSM matches; matches
                    field carries the list for the admin to inspect

    State is purely informational. Submit-to-OSM works in all three.
    """
    state: str
    matches: list[OsmPreflightMatch] = []


class QueueItemOut(BaseModel):
    """One item in the unified admin queue. Submissions and completion
    candidates share most fields; the `kind` discriminator + a few
    kind-specific fields cover what's different."""
    kind: str  # "submission" | "completion_candidate"
    # Stable identifier the UI uses for action URLs. For submissions:
    # submission_id. For completion candidates: place_id.
    id: uuid.UUID
    place_id: uuid.UUID
    name: str
    category: str | None
    description: str | None = None
    external_link: str | None = None
    # Where the place originally came from.
    source: str  # "community" | "wikipedia" | "gnis" | "other"
    lat: float
    lng: float
    maps_url: str
    photo_url: str
    card_url: str | None = None
    # Who's associated with the item — for submissions, the submitter;
    # for completion candidates, the most-recent completer.
    actor_callsign: str
    actor_style: str
    # When the relevant event happened (submitted_at OR completed_at).
    occurred_at: str
    # OSM publish gates (same shape as the prior PendingSubmissionOut).
    osm_publishable: bool = False
    osm_picker: list[dict] | None = None
    osm_already_published_node_id: int | None = None
    # Pre-flight: did we find anything similar already on OSM near this
    # location? Submission items have real data (populated by background
    # task post-submit); completion candidates inherit None for now
    # (they came from a discover pipeline that doesn't run pre-flight).
    osm_preflight: OsmPreflightInfo | None = None


@router.get("/queue", response_model=list[QueueItemOut])
async def list_queue(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[QueueItemOut]:
    """Unified queue: pending Submissions FIFO + completion candidates
    newest-first. Submissions appear first within the response (they're
    the items the admin must explicitly action — Approve / Return /
    Submit-to-OSM); completion candidates are passive (Skip or
    Submit-to-OSM, no Return)."""
    out: list[QueueItemOut] = []

    # --- Pending submissions ---
    lat_col = func.ST_Y(cast(Place.coordinates, Geometry))
    lng_col = func.ST_X(cast(Place.coordinates, Geometry))
    sub_rows = (
        await db.execute(
            select(Submission, Place, User, lat_col, lng_col)
            .join(Place, Place.id == Submission.place_id)
            .join(User, User.id == Submission.user_id)
            .where(Submission.status == SubmissionStatus.PENDING.value)
            .order_by(Submission.submitted_at.asc())
        )
    ).all()
    for submission, place, submitter, lat, lng in sub_rows:
        picker = osm_tagging.picker_choices(place.category)
        publishable = (
            picker is not None
            or osm_tagging.tags_for_publish(
                category=place.category, place_name=place.name or "",
            ) is not None
        )
        # Map persisted columns to the three pre-flight states.
        if submission.osm_preflight_checked_at is None:
            preflight = OsmPreflightInfo(state="pending")
        elif not submission.osm_preflight_matches:
            preflight = OsmPreflightInfo(state="clear")
        else:
            preflight = OsmPreflightInfo(
                state="matches",
                matches=[
                    OsmPreflightMatch(**m)
                    for m in submission.osm_preflight_matches
                ],
            )
        out.append(
            QueueItemOut(
                kind="submission",
                id=submission.id,
                place_id=place.id,
                name=place.name or "",
                category=place.category,
                description=submission.description,
                external_link=submission.external_link,
                source="community",
                lat=float(lat),
                lng=float(lng),
                maps_url=(
                    f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lng:.6f}"
                    f"#map=19/{lat:.6f}/{lng:.6f}"
                ),
                photo_url=f"/submissions/{submission.id}/photo.jpg",
                card_url=f"/submissions/{submission.id}/card.jpg",
                actor_callsign=submitter.callsign,
                actor_style=submitter.adventure_style,
                occurred_at=submission.submitted_at.isoformat(),
                osm_publishable=publishable,
                osm_picker=picker,
                osm_already_published_node_id=place.osm_published_node_id,
                osm_preflight=preflight,
            )
        )

    # --- Completion-driven candidates ---
    for cand in await osm_candidates.list_candidates(db):
        picker = osm_tagging.picker_choices(cand.place.category)
        publishable = (
            picker is not None
            or osm_tagging.tags_for_publish(
                category=cand.place.category,
                place_name=cand.place.name or "",
                place_osm_type=cand.place.osm_type,
            ) is not None
        )
        # For Wikipedia-sourced candidates, auto-derive a clickable link
        # so the reviewer can verify the article before publishing.
        external_link: str | None = None
        if cand.place.osm_type == "wp" and cand.place.name:
            # name is the article title; spaces → underscores for URL.
            slug = cand.place.name.replace(" ", "_")
            external_link = f"https://en.wikipedia.org/wiki/{slug}"
        out.append(
            QueueItemOut(
                kind="completion_candidate",
                # place_id is the action key here (no submission to reference).
                id=cand.place.id,
                place_id=cand.place.id,
                name=cand.place.name or "",
                category=cand.place.category,
                description=cand.place.description,
                external_link=external_link,
                source=osm_candidates.source_label(cand.place.osm_type),
                lat=cand.lat,
                lng=cand.lng,
                maps_url=(
                    f"https://www.openstreetmap.org/"
                    f"?mlat={cand.lat:.6f}&mlon={cand.lng:.6f}"
                    f"#map=19/{cand.lat:.6f}/{cand.lng:.6f}"
                ),
                # Reuse the completion's mission card so the reviewer sees
                # what the user actually captured. No card.jpg side-render
                # — the card is shown by the card endpoint on completions.
                photo_url=f"/missions/completions/{cand.completion.id}/photo.jpg",
                card_url=None,
                actor_callsign=cand.completer.callsign,
                actor_style=cand.completer.adventure_style,
                occurred_at=cand.completion.completed_at.isoformat(),
                osm_publishable=publishable,
                osm_picker=picker,
                osm_already_published_node_id=cand.place.osm_published_node_id,
            )
        )

    return out


class SkipOut(BaseModel):
    place_id: uuid.UUID
    osm_skipped_at: str


@router.post("/places/{place_id}/skip-osm", response_model=SkipOut)
async def skip_osm(
    place_id: uuid.UUID,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SkipOut:
    """Mark this place as 'no thanks' for OSM. Removes it from the
    candidate queue permanently (until manually cleared in the DB).
    Does not affect the place's status in our local dispatch pool —
    users can still get dispatched there; we just won't push it
    upstream."""
    place = (
        await db.execute(select(Place).where(Place.id == place_id))
    ).scalar_one_or_none()
    if place is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "place not found")
    updated = await osm_candidates.mark_skipped(db=db, place=place, admin=admin)
    return SkipOut(
        place_id=updated.id,
        osm_skipped_at=updated.osm_skipped_at.isoformat(),
    )


@router.post(
    "/places/{place_id}/publish-osm", response_model=OsmPublishOut,
)
async def publish_place_osm(
    place_id: uuid.UUID,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    picker_choice: Annotated[str | None, Form()] = None,
) -> OsmPublishOut:
    """Push a completion-driven candidate place to OSM. No local approval
    needed — the place is already in our DB and active. Reuses the same
    publish service as the submission path with submission=None."""
    lat_col = func.ST_Y(cast(Place.coordinates, Geometry))
    lng_col = func.ST_X(cast(Place.coordinates, Geometry))
    row = (
        await db.execute(
            select(Place, lat_col, lng_col).where(Place.id == place_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "place not found")
    place, lat, lng = row

    try:
        pub = await osm_publish.publish_place_to_osm(
            db=db,
            settings=settings,
            place=place,
            lat=float(lat),
            lng=float(lng),
            reviewer=admin,
            submission=None,
            picker_choice=picker_choice,
        )
    except osm_publish.OsmDailyCapReachedError as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e)) from e
    except osm_publish.OsmPublishError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    except osm_oauth.OsmAuthError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e

    return OsmPublishOut(
        # No submission so the id field carries place_id instead for
        # frontend correlation.
        id=place.id,
        status="published",
        osm_changeset_id=pub.changeset_id,
        osm_node_id=pub.node_id,
        osm_dry_run=pub.dry_run,
        osm_tags=dict(pub.tags_json),
    )

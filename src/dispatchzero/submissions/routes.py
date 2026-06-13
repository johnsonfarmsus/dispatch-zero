"""POST /submissions/capture + GET endpoints for a submitter's own card/photo.

Submission lifecycle is:
- POST /submissions/capture          create + persist photo + compose PENDING card
- GET  /submissions                  list the submitter's own submissions
- GET  /submissions/{id}             read the submission (self or admin)
- GET  /submissions/{id}/photo.jpg   raw thumbnail (self or admin)
- GET  /submissions/{id}/card.jpg    composed contribution card (self or admin)

Approval / rejection / OSM publishing live in services.submissions and are
driven from the in-app admin review queue (dispatchzero.admin.routes), gated
by require_admin. A break-glass CLI (dispatchzero.tools.review_submissions)
also exists for server-side review without the UI.
"""
import logging
import uuid
from pathlib import Path
from typing import Annotated, Literal

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.deps import current_user
from dispatchzero.config import Settings, get_settings
from dispatchzero.db import get_session
from dispatchzero.models import Place, PlaceCategory, Submission, User
from dispatchzero.ratelimit import RateLimitExceeded, check_and_increment
from dispatchzero.services.photo import PhotoTooLargeError
from dispatchzero.services.submissions import (
    SubmissionNotFoundError,
    SubmissionRejectedError,
    create_submission,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/submissions", tags=["submissions"])


async def _get_redis(
    settings: Annotated[Settings, Depends(get_settings)],
) -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


class SubmissionOut(BaseModel):
    id: uuid.UUID
    # Nullable because the linked Place is hard-deleted when a submission is
    # Returned (see services.submissions.reject_submission). The submitter's
    # dossier still renders the card via place_name_snapshot in that case.
    place_id: uuid.UUID | None = None
    status: str
    description: str | None
    external_link: str | None = None
    share_token: str
    submitted_at: str  # ISO 8601
    # Optional reviewer note shown alongside the RETURNED stamp on the
    # submitter's dossier card. None for pending / approved submissions
    # and for returned ones where the reviewer didn't leave a note.
    review_note: str | None = None
    # Set once this submission's place has been published to OpenStreetMap.
    # The submitter sees a "Now on OpenStreetMap" moment + a link to their
    # live node. This is the round-trip's payoff surfaced to the person who
    # earned it. None until/unless a real (non-dry-run) publish landed.
    osm_node_id: int | None = None


class SubmissionListItem(BaseModel):
    """Slimmer payload for dossier-list rendering. Mirrors CompletionListItem
    so the frontend can stack both into one list ordered by date."""
    id: uuid.UUID
    place_id: uuid.UUID | None = None
    place_name: str | None
    place_category: str
    description: str | None
    external_link: str | None = None
    status: str
    share_token: str
    submitted_at: str  # ISO 8601
    review_note: str | None = None


def _submission_to_out(s: Submission, *, osm_node_id: int | None = None) -> SubmissionOut:
    return SubmissionOut(
        id=s.id,
        place_id=s.place_id,
        status=s.status,
        description=s.description,
        external_link=s.external_link,
        share_token=s.share_token,
        submitted_at=s.submitted_at.isoformat(),
        review_note=s.review_note,
        osm_node_id=osm_node_id,
    )


async def _osm_node_id_for_submission(
    db: AsyncSession, submission_id: uuid.UUID,
) -> int | None:
    """The OSM node id this submission was published as, if any. Reads the
    audit log for a real (non-dry-run) publication with a node id. None
    when the submission was never published, or only dry-run published."""
    from dispatchzero.models import OsmPublication
    return (
        await db.execute(
            select(OsmPublication.node_id)
            .where(
                OsmPublication.submission_id == submission_id,
                OsmPublication.dry_run.is_(False),
                OsmPublication.node_id.is_not(None),
            )
            .order_by(OsmPublication.published_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


_CATEGORY_VALUES = Literal[
    "mural", "sculpture", "memorial", "historic", "viewpoint",
    "church", "park", "infrastructure", "civic",
]


@router.post("/capture", response_model=SubmissionOut)
async def capture(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[aioredis.Redis, Depends(_get_redis)],
    background_tasks: BackgroundTasks,
    photo: Annotated[UploadFile, File(description="Captured photo")],
    name: Annotated[str, Form(min_length=1, max_length=200)],
    category: Annotated[_CATEGORY_VALUES, Form()],
    lat: Annotated[float, Form(ge=-90.0, le=90.0)],
    lng: Annotated[float, Form(ge=-180.0, le=180.0)],
    description: Annotated[str | None, Form(max_length=140)] = None,
    link: Annotated[str | None, Form(max_length=500)] = None,
) -> SubmissionOut:
    """Submit a community POI.

    Coordinates come from the browser (navigator.geolocation), not from
    the photo's EXIF — most users don't enable Location for the iOS
    Camera app, but the browser can request its own location permission
    independently. The photo's EXIF DateTimeOriginal still has to be
    within the freshness window (anti-camera-roll).

    Returns the new Submission row immediately, status=pending. The user can
    fetch the composed contribution card at GET /submissions/{id}/card.jpg.
    """
    settings = get_settings()
    # Per-user daily cap: one account can't flood the queue or get our
    # server IP banned by Overpass via the background pre-flight.
    try:
        await check_and_increment(
            redis=redis, scope="submission_capture",
            identifier=str(user.id),
            max_count=settings.rate_limit_submission_per_day,
            window_seconds=86400,
        )
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="you've filed a lot of reports today — try again tomorrow",
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e

    raw = await photo.read()
    if not raw:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "photo upload is empty",
        )
    if len(raw) > settings.photo_max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "that image is too large — send a standard photo",
        )
    try:
        submission = await create_submission(
            db=db, user=user,
            raw_photo=raw,
            name=name,
            category=PlaceCategory(category),
            description=description,
            external_link=link,
            lat=lat,
            lng=lng,
        )
    except PhotoTooLargeError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "that image can't be processed — send a standard photo",
        ) from e
    except SubmissionRejectedError as e:
        # 422 to mirror the mission-capture failure shape — the upload
        # passed structural validation but failed semantic checks
        # (EXIF, freshness, content).
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    # Fire the OSM pre-flight check after the response goes out. The
    # background task owns its own DB session (the request's is gone by
    # then). Failure here doesn't surface to the user — the admin queue
    # will show the submission with "pre-flight pending" until either
    # the check finishes or stays unfinished forever (latter is rare).
    from dispatchzero.services.osm_preflight import run_for_submission
    background_tasks.add_task(run_for_submission, submission.id)

    return _submission_to_out(submission)


@router.get("", response_model=list[SubmissionListItem])
async def list_submissions(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[SubmissionListItem]:
    """The current user's submissions, newest first. The dossier screen
    fetches this alongside /missions/completions and merges the two lists
    by date so the user sees one unified history.

    LEFT JOIN on Place because Returned submissions can have a NULL place_id
    (the orphan Place was hard-deleted at return time — see
    services.submissions.reject_submission). When the live Place is gone,
    fall back to the place_name_snapshot stored on the Submission row."""
    rows = (
        await db.execute(
            select(Submission, Place)
            .outerjoin(Place, Place.id == Submission.place_id)
            .where(Submission.user_id == user.id)
            .order_by(Submission.submitted_at.desc())
            .limit(50)
        )
    ).all()
    return [
        SubmissionListItem(
            id=s.id,
            place_id=(p.id if p is not None else None),
            place_name=(p.name if p is not None else s.place_name_snapshot),
            place_category=(p.category if p is not None else "community"),
            description=s.description,
            external_link=s.external_link,
            status=s.status,
            share_token=s.share_token,
            submitted_at=s.submitted_at.isoformat(),
            review_note=s.review_note,
        )
        for s, p in rows
    ]


@router.get("/{submission_id}", response_model=SubmissionOut)
async def get_submission(
    submission_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SubmissionOut:
    submission = await _load_visible(db, submission_id, user)
    node_id = await _osm_node_id_for_submission(db, submission.id)
    return _submission_to_out(submission, osm_node_id=node_id)


@router.get("/{submission_id}/photo.jpg")
async def submission_photo(
    submission_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    submission = await _load_visible(db, submission_id, user)
    if not submission.photo_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo missing")
    photo_path = Path(submission.photo_url)
    if not photo_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo missing")
    return FileResponse(photo_path, media_type="image/jpeg")


@router.get("/{submission_id}/card.jpg")
async def submission_card(
    submission_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Composed contribution card. Status stamp tracks the workflow (PENDING /
    VERIFIED / RETURNED). The route doesn't regenerate — that happens in
    services.submissions when status changes."""
    submission = await _load_visible(db, submission_id, user)
    if not submission.card_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "card missing")
    card_path = Path(submission.card_path)
    if not card_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "card missing")
    return FileResponse(card_path, media_type="image/jpeg")


async def _load_visible(
    db: AsyncSession, submission_id: uuid.UUID, user: User,
) -> Submission:
    """Look up a submission that the requester is allowed to see.

    Submitters can see their own submissions; admins can see everyone's
    (needed so the /admin/* review queue can render photos + cards via
    these same endpoints rather than duplicating routes under /admin)."""
    submission = (
        await db.execute(select(Submission).where(Submission.id == submission_id))
    ).scalar_one_or_none()
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "submission not found")
    if submission.user_id != user.id and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your submission")
    return submission

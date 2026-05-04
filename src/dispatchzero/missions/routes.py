import logging
import uuid
from pathlib import Path
from typing import Annotated

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

from dispatchzero.auth.deps import current_user
from dispatchzero.config import Settings, get_settings
from dispatchzero.db import get_session
from dispatchzero.models import Completion, Mission, Place, User
from dispatchzero.ratelimit import RateLimitExceeded, check_and_increment
from dispatchzero.schemas.completions import (
    CompletionListItem,
    CompletionOut,
    DebriefOut,
    MissionRequestIn,
    RateIn,
)
from dispatchzero.schemas.missions import MissionGenerateIn, MissionOut, PlaceMini
from dispatchzero.services.cards import compose_mission_card
from dispatchzero.services.discovery import discover_nearby
from dispatchzero.services.rank import completions_to_rank, stats_at_completion
from dispatchzero.services.mission_flow import (
    CaptureFailedError,
    capture_mission,
    rate_completion,
    user_completions_count,
)
from dispatchzero.services.missions import (
    MissionGenerationError,
    get_or_generate_mission,
)

router = APIRouter(prefix="/missions", tags=["missions"])


async def _get_redis(
    settings: Annotated[Settings, Depends(get_settings)],
) -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def _place_lat_lng(db: AsyncSession, place_id: uuid.UUID) -> tuple[float, float]:
    """Read a Place's PostGIS geography column as (lat, lng)."""
    row = (
        await db.execute(
            text(
                "SELECT ST_Y(coordinates::geometry), ST_X(coordinates::geometry) "
                "FROM places WHERE id = :pid"
            ),
            {"pid": place_id},
        )
    ).one()
    return float(row[0]), float(row[1])


async def _mission_to_out(
    db: AsyncSession, mission: Mission, place: Place
) -> MissionOut:
    lat, lng = await _place_lat_lng(db, place.id)
    return MissionOut(
        id=mission.id,
        place_id=mission.place_id,
        place=PlaceMini(
            id=place.id,
            name=place.name,
            category=place.category,
            description=place.description,
            lat=lat,
            lng=lng,
        ),
        adventure_style=mission.adventure_style,
        dispatch_summary=mission.dispatch_summary,
        briefing_text=mission.briefing_text,
        clue=mission.clue,
        badge_framing=mission.badge_framing,
        audio_url=mission.audio_url,
        ai_model=mission.ai_model,
        status=mission.status,
    )


async def _fetch_place(db: AsyncSession, place_id: uuid.UUID) -> Place:
    return (
        await db.execute(select(Place).where(Place.id == place_id))
    ).scalar_one()


def _completion_to_out(c: Completion) -> CompletionOut:
    return CompletionOut(
        id=c.id,
        mission_id=c.mission_id,
        place_id=c.place_id,
        verified=c.verified,
        photo_url=c.photo_url,
        completed_at=c.completed_at.isoformat(),
        share_token=c.share_token,
    )


@router.post("/generate", response_model=MissionOut)
async def generate(
    payload: MissionGenerateIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[aioredis.Redis, Depends(_get_redis)],
) -> MissionOut:
    settings = get_settings()
    try:
        await check_and_increment(
            redis=redis, scope="mission_generate",
            identifier=str(user.id),
            max_count=settings.rate_limit_mission_generate_per_day,
            window_seconds=86400,
        )
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests, agent — stand by",
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e
    try:
        mission = await get_or_generate_mission(
            db=db,
            user=user,
            place_id=payload.place_id,
            adventure_style=payload.adventure_style,
        )
    except MissionGenerationError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the dispatch line is unreliable, agent — try again",
        ) from e
    place = await _fetch_place(db, mission.place_id)
    return await _mission_to_out(db, mission, place)


# Tiered fallback for /missions/request — try increasingly permissive searches
# until we find an eligible place. Each tier is (radius_m, source, broad).
# Tier 0 uses caller-supplied radius. Tiers 1-3 escalate scope: more radius,
# then broader OSM filters, then a different data source (Wikipedia geosearch).
#
# A tier "fails" and we move to the next either when:
#   1) the source returns no places at all, OR
#   2) every place returned has been completed by this user in the last 90 days
# (`discover_nearby` filters out completed places, so 0 returned = either case)
_REQUEST_TIERS: list[tuple[int, str, bool]] = [
    # (radius_m, source, broad)
    # Tier 0 is dynamic — uses payload.radius_m with overpass+strict
    (5000, "overpass", False),   # Tier 1: 5km strict OSM
    (5000, "overpass", True),    # Tier 2: 5km broad OSM (parks, peaks, churches, etc)
    (5000, "wikipedia", False),  # Tier 3: 5km Wikipedia geosearch (global coverage)
]


@router.post("/request", response_model=MissionOut)
async def request_mission(
    payload: MissionRequestIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[aioredis.Redis, Depends(_get_redis)],
) -> MissionOut:
    """Combined: discover nearby places, pick top, generate mission.

    Tiered fallback: caller's radius (strict OSM) → 5km strict OSM → 5km broad
    OSM → 5km Wikipedia geosearch. First tier with an eligible (named, not
    recently completed by this user) place wins. Silent escalation — caller
    gets a single mission response regardless of which tier succeeded.
    """
    settings = get_settings()
    try:
        await check_and_increment(
            redis=redis, scope="mission_request",
            identifier=str(user.id),
            max_count=settings.rate_limit_mission_request_per_day,
            window_seconds=86400,
        )
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests, agent — stand by",
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e
    tiers = [(payload.radius_m, "overpass", False)] + _REQUEST_TIERS
    seen: set[tuple[int, str, bool]] = set()
    places: list = []
    for radius_m, source, broad in tiers:
        key = (radius_m, source, broad)
        if key in seen:
            continue
        seen.add(key)
        try:
            places = await discover_nearby(
                db=db, redis=redis, user=user,
                lat=payload.lat, lng=payload.lng,
                radius_m=radius_m, limit=1, broad=broad, source=source,
            )
        except httpx.HTTPError as e:
            # Transient upstream failure (timeout, connection reset, etc.)
            # Don't kill the whole request — let the next tier try.
            log.warning(
                "discover tier failed (radius=%dm source=%s broad=%s): %s",
                radius_m, source, broad, e,
            )
            places = []
        if places:
            break

    if not places:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no eligible places nearby")
    place_id = places[0]["id"]
    try:
        mission = await get_or_generate_mission(
            db=db, user=user, place_id=place_id,
            adventure_style=payload.adventure_style,
        )
    except MissionGenerationError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the dispatch line is unreliable, agent — try again",
        ) from e
    place = await _fetch_place(db, mission.place_id)
    return await _mission_to_out(db, mission, place)


# History dossier — list of the user's recent completions and the per-completion
# detail used by the Dossier screens. Declared BEFORE /{mission_id} so the
# router doesn't try to interpret "completions" as a mission UUID.
_HISTORY_LIMIT = 50


@router.get("/completions", response_model=list[CompletionListItem])
async def list_completions(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[CompletionListItem]:
    """Return the user's most recent completions, newest first."""
    rows = (
        await db.execute(
            select(Completion, Place, Mission)
            .join(Place, Place.id == Completion.place_id)
            .join(Mission, Mission.id == Completion.mission_id)
            .where(Completion.user_id == user.id)
            .order_by(Completion.completed_at.desc())
            .limit(_HISTORY_LIMIT)
        )
    ).all()
    return [
        CompletionListItem(
            id=c.id,
            place_id=p.id,
            place_name=p.name,
            place_category=p.category,
            completed_at=c.completed_at.isoformat(),
            share_token=c.share_token,
            badge_framing=m.badge_framing,
            adventure_style=m.adventure_style,
        )
        for c, p, m in rows
    ]


@router.get("/completions/{completion_id}", response_model=CompletionListItem)
async def get_completion(
    completion_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> CompletionListItem:
    """Single completion detail — owner only. Same shape as list items."""
    row = (
        await db.execute(
            select(Completion, Place, Mission)
            .join(Place, Place.id == Completion.place_id)
            .join(Mission, Mission.id == Completion.mission_id)
            .where(Completion.id == completion_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "completion not found")
    c, p, m = row
    if c.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your completion")
    return CompletionListItem(
        id=c.id,
        place_id=p.id,
        place_name=p.name,
        place_category=p.category,
        completed_at=c.completed_at.isoformat(),
        share_token=c.share_token,
        badge_framing=m.badge_framing,
        adventure_style=m.adventure_style,
    )


@router.get("/completions/{completion_id}/photo.jpg")
async def completion_photo(
    completion_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Serve the saved 600px capture as a small thumbnail for list views."""
    completion = (
        await db.execute(select(Completion).where(Completion.id == completion_id))
    ).scalar_one_or_none()
    if completion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "completion not found")
    if completion.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your completion")
    if not completion.photo_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo missing")
    photo_path = Path(completion.photo_url)
    if not photo_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo missing")
    return FileResponse(photo_path, media_type="image/jpeg")


@router.get("/{mission_id}", response_model=MissionOut)
async def get_mission(
    mission_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MissionOut:
    mission = (
        await db.execute(select(Mission).where(Mission.id == mission_id))
    ).scalar_one_or_none()
    if mission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    place = await _fetch_place(db, mission.place_id)
    return await _mission_to_out(db, mission, place)


@router.post("/{mission_id}/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_mission(
    mission_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """v1: no-op success. Validates mission exists so the client gets a clean 404."""
    m = (await db.execute(select(Mission).where(Mission.id == mission_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")


@router.post("/{mission_id}/capture", response_model=DebriefOut)
async def capture(
    mission_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    photo: UploadFile = File(...),
    lat: float = Form(...),
    lng: float = Form(...),
    accuracy_m: float | None = Form(None),
) -> DebriefOut:
    mission = (
        await db.execute(select(Mission).where(Mission.id == mission_id))
    ).scalar_one_or_none()
    if mission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    place = (
        await db.execute(select(Place).where(Place.id == mission.place_id))
    ).scalar_one()

    raw = await photo.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty photo upload")

    try:
        completion = await capture_mission(
            db=db, user=user, mission=mission, place=place,
            raw_photo=raw,
            capture_lat=lat, capture_lng=lng, capture_accuracy_m=accuracy_m,
        )
    except CaptureFailedError as e:
        # In-character to the client: don't leak GPS vs EXIF.
        # Server-side: log the actual reason so we can debug from the logs.
        log.info(
            "capture rejected mission_id=%s user_id=%s reason=%s",
            mission_id, user.id, e,
        )
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "the proof is not yet sufficient, agent — try again",
        ) from e

    refreshed = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
    count = await user_completions_count(db, user_id=user.id)
    return DebriefOut(
        completion=_completion_to_out(completion),
        user_completions_count=count,
        user_missions_this_week=refreshed.missions_this_week,
    )


@router.post("/completions/{completion_id}/rate", response_model=CompletionOut)
async def rate(
    completion_id: uuid.UUID,
    payload: RateIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> CompletionOut:
    completion = (
        await db.execute(select(Completion).where(Completion.id == completion_id))
    ).scalar_one_or_none()
    if completion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "completion not found")
    if completion.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your completion")

    await rate_completion(
        db=db, user=user, completion=completion,
        location_rating=payload.location_rating,
        mission_rating=payload.mission_rating,
        location_reason=payload.location_reason,
        mission_reason=payload.mission_reason,
    )
    return _completion_to_out(completion)


@router.get("/completions/{completion_id}/card.jpg")
async def completion_card(
    completion_id: uuid.UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Return the 4:5 mission card JPEG for the user's own completion.

    Generated at capture time; regenerated on demand if missing on disk
    (e.g. an older completion or a card-gen failure during capture).
    """
    completion = (
        await db.execute(select(Completion).where(Completion.id == completion_id))
    ).scalar_one_or_none()
    if completion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "completion not found")
    if completion.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your completion")

    settings = get_settings()
    card_path = Path(settings.photo_upload_dir) / "cards" / f"{completion.id}.jpg"
    if not card_path.exists():
        # Regenerate on miss. Need place + mission + user to compose.
        mission = (
            await db.execute(select(Mission).where(Mission.id == completion.mission_id))
        ).scalar_one()
        place = (
            await db.execute(select(Place).where(Place.id == completion.place_id))
        ).scalar_one()
        photo_path = Path(completion.photo_url) if completion.photo_url else None
        if photo_path is None or not photo_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "photo missing")
        # Snapshot stats at this completion's moment — the row is already
        # in the DB so include_self=True (counts <= at_time include this one).
        total_then, week_then = await stats_at_completion(
            db, user_id=completion.user_id,
            at_time=completion.completed_at, include_self=True,
        )
        rank_then = completions_to_rank(total_then)
        try:
            compose_mission_card(
                photo_path=photo_path,
                place_name=place.name or "Unmarked target",
                callsign=user.callsign,
                completed_at=completion.completed_at,
                adventure_style=mission.adventure_style,
                rank_at_completion=rank_then,
                completions_total=total_then,
                completions_this_week=week_then,
                dispatch_summary=mission.dispatch_summary,
                output_path=card_path,
            )
        except Exception as e:
            log.warning("card regen failed completion_id=%s: %s", completion_id, e)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "card unavailable"
            ) from e

    return FileResponse(card_path, media_type="image/jpeg")

import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.deps import current_user
from dispatchzero.config import Settings, get_settings
from dispatchzero.db import get_session
from dispatchzero.models import Completion, Mission, Place, User
from dispatchzero.schemas.completions import (
    CompletionOut,
    DebriefOut,
    MissionRequestIn,
    RateIn,
)
from dispatchzero.schemas.missions import MissionGenerateIn, MissionOut, PlaceMini
from dispatchzero.services.discovery import discover_nearby
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
    )


@router.post("/generate", response_model=MissionOut)
async def generate(
    payload: MissionGenerateIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MissionOut:
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
# until we find an eligible place. Each tier is (radius_m, broad_filters).
# The user's `payload.radius_m` controls the FIRST tier only; subsequent tiers
# always use a wider radius. This way a user-supplied 2km still gets the
# graceful expansion when they're in a sparse area.
_REQUEST_TIERS: list[tuple[int, bool]] = [
    # (radius_m, broad)
    # Tier 0 is dynamic — uses payload.radius_m
    (5000, False),  # Tier 1: 5km strict
    (5000, True),   # Tier 2: 5km broad
    (10000, True),  # Tier 3: 10km broad
]


@router.post("/request", response_model=MissionOut)
async def request_mission(
    payload: MissionRequestIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[aioredis.Redis, Depends(_get_redis)],
) -> MissionOut:
    """Combined: discover nearby places, pick top, generate mission.

    Tiered fallback: caller's radius (strict) → 5km strict → 5km broad → 10km broad.
    First tier with an eligible place wins. Silent escalation — caller gets a
    single mission response regardless of which tier succeeded.
    """
    tiers = [(payload.radius_m, False)] + _REQUEST_TIERS
    seen_radii: set[tuple[int, bool]] = set()
    places: list = []
    for radius_m, broad in tiers:
        key = (radius_m, broad)
        if key in seen_radii:
            continue  # skip duplicates (e.g. payload.radius_m=5000 + tier 1)
        seen_radii.add(key)
        places = await discover_nearby(
            db=db, redis=redis, user=user,
            lat=payload.lat, lng=payload.lng,
            radius_m=radius_m, limit=1, broad=broad,
        )
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
        # In-character: don't leak whether GPS or EXIF failed
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
    )
    return _completion_to_out(completion)

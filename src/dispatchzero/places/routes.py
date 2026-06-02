import uuid
from typing import Annotated, Literal

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.deps import current_user
from dispatchzero.config import Settings, get_settings
from dispatchzero.db import get_session
from dispatchzero.models import ExclusionReason, User
from dispatchzero.schemas.places import PlaceOut
from dispatchzero.services.discovery import discover_nearby
from dispatchzero.services.place_reports import PlaceNotFoundError, report_place

router = APIRouter(prefix="/places", tags=["places"])


class PlaceReportIn(BaseModel):
    """Why the user is excluding this place. Same vocabulary as the
    post-completion survey's location_reason so the global flag rule
    treats both inputs uniformly."""
    reason: Literal["unreachable", "not_found"]


class PlaceReportOut(BaseModel):
    place_id: uuid.UUID
    reason: str
    reported_at: str  # ISO 8601


async def _get_redis(
    settings: Annotated[Settings, Depends(get_settings)],
) -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


@router.post("/{place_id}/report", response_model=PlaceReportOut)
async def report(
    place_id: uuid.UUID,
    payload: PlaceReportIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> PlaceReportOut:
    """Report a place as gone / inaccessible / never findable.

    Per-user permanent exclusion: this user will never be dispatched to
    this place again. Also contributes to the global auto-flag rule —
    two distinct users reporting 'unreachable' (via this endpoint OR via
    a post-completion 👎) flags the place for maintainer review.

    Idempotent: re-reporting updates the stored reason.
    """
    try:
        exclusion = await report_place(
            db=db, user=user, place_id=place_id,
            reason=ExclusionReason(payload.reason),
        )
    except PlaceNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return PlaceReportOut(
        place_id=exclusion.place_id,
        reason=exclusion.reason,
        reported_at=exclusion.reported_at.isoformat(),
    )


@router.get("/nearby", response_model=list[PlaceOut])
async def nearby(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[aioredis.Redis, Depends(_get_redis)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    radius_m: Annotated[int, Query(ge=100, le=10000)] = 2000,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict]:
    return await discover_nearby(
        db=db, redis=redis, user=user,
        lat=lat, lng=lng, radius_m=radius_m, limit=limit,
    )

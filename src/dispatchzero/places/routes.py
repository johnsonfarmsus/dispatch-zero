from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.deps import current_user
from dispatchzero.config import Settings, get_settings
from dispatchzero.db import get_session
from dispatchzero.models import User
from dispatchzero.schemas.places import PlaceOut
from dispatchzero.services.discovery import discover_nearby

router = APIRouter(prefix="/places", tags=["places"])


async def _get_redis(
    settings: Annotated[Settings, Depends(get_settings)],
) -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


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

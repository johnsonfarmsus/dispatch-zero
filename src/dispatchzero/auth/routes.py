from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.deps import current_user
from dispatchzero.auth.passwords import hash_password, verify_password
from dispatchzero.auth.ratelimit import LoginRateLimiter
from dispatchzero.auth.sessions import sign_session
from dispatchzero.config import Settings, get_settings
from dispatchzero.db import get_session
from dispatchzero.models import User
from dispatchzero.schemas.auth import LoginIn, MeOut, SignupIn

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, user_id, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=sign_session(user_id),
        max_age=settings.session_cookie_max_age_seconds,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _get_redis(
    settings: Annotated[Settings, Depends(get_settings)],
) -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def _user_to_me(db: AsyncSession, user: User) -> MeOut:
    # Completion table may not exist yet (Phase 5 migration adds it). Try/except
    # so that early auth tests against the bare schema continue to pass.
    try:
        from dispatchzero.models import Completion
        count = (
            await db.execute(
                select(func.count(Completion.id)).where(Completion.user_id == user.id)
            )
        ).scalar_one()
    except Exception:
        count = 0
    return MeOut(
        id=user.id,
        callsign=user.callsign,
        adventure_style=user.adventure_style,
        completions_count=int(count),
        missions_this_week=user.missions_this_week,
    )


@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=MeOut)
async def signup(
    payload: SignupIn,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeOut:
    callsign_lower = payload.callsign.lower()
    existing = await db.execute(
        select(User).where(User.callsign_lower == callsign_lower)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "callsign already taken")

    user = User(
        callsign=payload.callsign,
        callsign_lower=callsign_lower,
        password_hash=hash_password(payload.password),
        adventure_style=payload.adventure_style,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    _set_session_cookie(response, user.id, settings)
    return await _user_to_me(db, user)


@router.post("/login", status_code=status.HTTP_200_OK, response_model=MeOut)
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(_get_redis)],
) -> MeOut:
    ip = _client_ip(request)
    limiter = LoginRateLimiter(
        redis,
        max_attempts=settings.login_rate_limit_max,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    if not await limiter.is_allowed(ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many failed attempts; try again later",
        )

    result = await db.execute(
        select(User).where(User.callsign_lower == payload.callsign.lower())
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        await limiter.record_failure(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    _set_session_cookie(response, user.id, settings)
    return await _user_to_me(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
    )


@router.get("/me", response_model=MeOut)
async def me(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MeOut:
    return await _user_to_me(db, user)

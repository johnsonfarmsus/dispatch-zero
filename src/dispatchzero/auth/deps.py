import uuid
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.sessions import verify_session
from dispatchzero.config import get_settings
from dispatchzero.db import get_session
from dispatchzero.models import User


async def current_user(
    db: Annotated[AsyncSession, Depends(get_session)],
    dz_session: Annotated[str | None, Cookie()] = None,
) -> User:
    if dz_session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")

    settings = get_settings()
    user_id: uuid.UUID | None = verify_session(
        dz_session, max_age_seconds=settings.session_cookie_max_age_seconds
    )
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session invalid or expired")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
    return user

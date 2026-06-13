"""GET /badges — the current user's computed badge collection.

Badges are derived from completion history (services.badges), so this is a
read-only projection. Grouped by family with an earned/total summary the
dossier renders as a fillable collection.
"""
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.deps import current_user
from dispatchzero.db import get_session
from dispatchzero.models import User
from dispatchzero.services.badges import compute_badges

router = APIRouter(prefix="/badges", tags=["badges"])


class BadgeOut(BaseModel):
    key: str
    name: str
    family: str
    description: str
    earned: bool
    current: int
    target: int


class BadgesResponse(BaseModel):
    earned_count: int
    total_count: int
    badges: list[BadgeOut]


@router.get("", response_model=BadgesResponse)
async def list_badges(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> BadgesResponse:
    badges = await compute_badges(db, user_id=user.id)
    earned = sum(1 for b in badges if b.earned)
    return BadgesResponse(
        earned_count=earned,
        total_count=len(badges),
        badges=[
            BadgeOut(
                key=b.key, name=b.name, family=b.family,
                description=b.description, earned=b.earned,
                current=b.current, target=b.target,
            )
            for b in badges
        ],
    )

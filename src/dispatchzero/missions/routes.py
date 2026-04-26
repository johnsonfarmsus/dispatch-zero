from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.deps import current_user
from dispatchzero.db import get_session
from dispatchzero.models import User
from dispatchzero.schemas.missions import MissionGenerateIn, MissionOut
from dispatchzero.services.missions import (
    MissionGenerationError,
    get_or_generate_mission,
)

router = APIRouter(prefix="/missions", tags=["missions"])


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
        msg = str(e).lower()
        if "not found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the dispatch line is unreliable, agent — try again",
        ) from e

    return MissionOut(
        id=mission.id,
        place_id=mission.place_id,
        adventure_style=mission.adventure_style,
        dispatch_summary=mission.dispatch_summary,
        briefing_text=mission.briefing_text,
        clue=mission.clue,
        badge_framing=mission.badge_framing,
        audio_url=mission.audio_url,
        ai_model=mission.ai_model,
        status=mission.status,
    )

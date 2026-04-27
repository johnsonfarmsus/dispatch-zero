import re
import uuid
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.config import get_settings
from dispatchzero.integrations.ollama import OllamaClient, OllamaError
from dispatchzero.models import Mission, MissionStatus, Place, User
from dispatchzero.schemas.missions import MissionContent
from dispatchzero.services.mission_prompts import build_mission_prompt

AdventureStyle = Literal["pulp", "agency", "guild"]


class MissionGenerationError(RuntimeError):
    """Raised when a mission cannot be produced (place not found, Ollama failure, validation failure)."""


async def get_or_generate_mission(
    *,
    db: AsyncSession,
    user: User,
    place_id: uuid.UUID,
    adventure_style: AdventureStyle | None,
) -> Mission:
    """Library hit if available, otherwise generate fresh via Ollama and persist."""
    style = adventure_style or user.adventure_style

    place = (
        await db.execute(select(Place).where(Place.id == place_id))
    ).scalar_one_or_none()
    if place is None:
        raise MissionGenerationError(f"place {place_id} not found")

    library_hit = await _library_lookup(db, place_id=place_id, style=style)
    if library_hit is not None:
        return library_hit

    settings = get_settings()
    client = OllamaClient(
        api_key=settings.ollama_api_key,
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    try:
        messages = build_mission_prompt(
            style=style,
            callsign=user.callsign,
            place_name=place.name or "an unnamed place",
            place_category=place.category,
            place_description=place.description,
            place_lat=0.0,  # not shipped to LLM by default; place_name carries the narrative weight
            place_lng=0.0,
        )
        try:
            raw = await client.chat(messages)
        except OllamaError as e:
            raise MissionGenerationError(f"ollama call failed: {e}") from e
    finally:
        await client.aclose()

    cleaned = _strip_markdown_fences(raw)
    try:
        content = MissionContent.model_validate_json(cleaned)
    except ValidationError as e:
        raise MissionGenerationError(f"ollama returned invalid mission shape: {e}") from e

    mission = Mission(
        place_id=place.id,
        adventure_style=style,
        dispatch_summary=content.dispatch_summary,
        briefing_text=content.briefing_text,
        clue=content.clue,
        badge_framing=content.badge_framing,
        ai_model=settings.ollama_model,
    )
    db.add(mission)
    await db.commit()
    await db.refresh(mission)
    return mission


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def _strip_markdown_fences(s: str) -> str:
    """Some models (esp. reasoning models) wrap JSON in ```json ... ``` despite
    response_format=json_object. Defensive parse: unwrap if wrapped, else return as-is."""
    m = _FENCE_RE.match(s.strip())
    if m:
        return m.group(1)
    return s


async def _library_lookup(
    db: AsyncSession, *, place_id: uuid.UUID, style: str
) -> Mission | None:
    """Return the best-loved still-active mission for this place+style, if any."""
    stmt = (
        select(Mission)
        .where(
            Mission.place_id == place_id,
            Mission.adventure_style == style,
            Mission.status == MissionStatus.ACTIVE.value,
            Mission.mission_thumbs_down < 3,
        )
        .order_by(Mission.mission_thumbs_up.desc(), Mission.created_at.asc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()

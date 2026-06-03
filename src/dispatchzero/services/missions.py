import json
import re
import uuid
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.config import get_settings
from dispatchzero.integrations.ollama import OllamaClient, OllamaError
from dispatchzero.models import Mission, MissionStatus, Place, User, UserPlaceHistory
from dispatchzero.schemas.missions import MissionContent
from dispatchzero.services.mission_prompts import build_mission_prompt

AdventureStyle = Literal["pulp", "agency", "guild"]


class MissionGenerationError(RuntimeError):
    """Raised when a mission cannot be produced (place not found, Ollama failure, validation failure)."""


# Grammar-forced schema for the briefing payload. Intentionally shape-only:
# `additionalProperties: false` + required fields + types + anyOf for nullables.
# Length bounds are NOT in the grammar — they live in MissionContent's Pydantic
# validators and are enforced post-parse with a repair retry, because llama.cpp
# (the backend the OLMo box runs on) crashes on combined nullability + length
# constraints in GBNF. See ollama.py module docstring.
_MISSION_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["dispatch_summary", "briefing_text", "clue", "badge_framing", "teaser"],
    "properties": {
        "dispatch_summary": {"type": "string"},
        "briefing_text": {"type": "string"},
        "clue": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "badge_framing": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "teaser": {"type": "string"},
    },
}

# Appended to the last user message when the first attempt's output fails to
# parse or fails Pydantic validation. Pushes the model to recover from
# over-length or malformed output without re-running the whole prompt.
_REPAIR_NUDGE = (
    "Return ONLY the JSON object with exactly these five fields "
    "(dispatch_summary, briefing_text, clue, badge_framing, teaser). "
    "No prose, no markdown, no commentary. "
    "dispatch_summary must be at most 400 characters. "
    "briefing_text must be at most 2200 characters. "
    "clue at most 240 characters or null. "
    "badge_framing at most 120 characters or null. "
    "teaser at most 140 characters (a single in-voice sentence that names the place)."
)


async def get_or_generate_mission(
    *,
    db: AsyncSession,
    user: User,
    place_id: uuid.UUID,
    adventure_style: AdventureStyle | None,
) -> Mission:
    """Return a mission for this (user, place, style).

    First-visit (no prior completion of this place by this user):
        Library hit if available; otherwise generate fresh, save to library,
        return. The library cache is shared across users, so a place loved
        by one user serves a free pre-warm to the next.

    Repeat-visit (user has prior completion):
        Bypass library, always generate fresh with follow-up framing
        ('secondary sweep', 'the file is reopened', etc.). The resulting
        mission is marked `repeat_visit=True` and EXCLUDED from future
        library lookups so a first-time visitor never sees a "back again"
        briefing that doesn't fit their context.
    """
    style = adventure_style or user.adventure_style

    place = (
        await db.execute(select(Place).where(Place.id == place_id))
    ).scalar_one_or_none()
    if place is None:
        raise MissionGenerationError(f"place {place_id} not found")

    is_repeat = await _user_has_visited(db, user_id=user.id, place_id=place_id)

    if not is_repeat:
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
            repeat_visit=is_repeat,
        )
        content = await _generate_with_repair(client, messages)
        content = _ensure_signoff(content, style=style)
    finally:
        await client.aclose()

    mission = Mission(
        place_id=place.id,
        adventure_style=style,
        dispatch_summary=content.dispatch_summary,
        briefing_text=content.briefing_text,
        clue=content.clue,
        badge_framing=content.badge_framing,
        teaser=content.teaser,
        ai_model=settings.ollama_model,
        repeat_visit=is_repeat,
    )
    db.add(mission)
    await db.commit()
    await db.refresh(mission)
    return mission


async def _user_has_visited(
    db: AsyncSession, *, user_id: uuid.UUID, place_id: uuid.UUID
) -> bool:
    """True if user_place_history has any row for (user, place) — meaning the
    user has at least one prior completion of this place. Doesn't care how
    long ago; the goal is briefing tone, not eligibility."""
    row = (
        await db.execute(
            select(UserPlaceHistory.id).where(
                UserPlaceHistory.user_id == user_id,
                UserPlaceHistory.place_id == place_id,
            ).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def _strip_markdown_fences(s: str) -> str:
    """Some models (esp. reasoning models) wrap JSON in ```json ... ``` despite
    response_format=json_object. Defensive parse: unwrap if wrapped, else return as-is."""
    m = _FENCE_RE.match(s.strip())
    if m:
        return m.group(1)
    return s


async def _generate_with_repair(
    client: OllamaClient, messages: list[dict[str, str]]
) -> MissionContent:
    """Grammar-forced briefing generation with a single repair retry.

    First attempt: grammar-constrained via JSON schema (caps the shape). On
    JSON-parse or Pydantic-validation failure (typically over-length text), we
    re-ask once with an appended length-and-format reminder before surfacing
    a MissionGenerationError. Small models (13B-class) trip the length caps
    noticeably more often than the 120B cloud model; the repair retry brings
    the practical success rate back into "essentially always" territory.

    The transport-level retry inside OllamaClient (5xx / transient) is
    distinct from this — this is the semantic retry, applied on top.
    """
    try:
        raw = await client.chat_structured(
            messages, schema=_MISSION_JSON_SCHEMA, schema_name="mission_content"
        )
    except OllamaError as e:
        raise MissionGenerationError(f"ollama call failed: {e}") from e

    content = _try_parse(raw)
    if content is not None:
        return content

    # Repair pass — append the length+format reminder to the last user message
    # and try once more. The system prompt is unchanged, so persona/voice
    # constraints still apply.
    repaired = list(messages)
    if repaired and repaired[-1].get("role") == "user":
        repaired[-1] = {
            **repaired[-1],
            "content": repaired[-1]["content"] + "\n\n" + _REPAIR_NUDGE,
        }
    else:
        repaired.append({"role": "user", "content": _REPAIR_NUDGE})

    try:
        raw2 = await client.chat_structured(
            repaired, schema=_MISSION_JSON_SCHEMA, schema_name="mission_content"
        )
    except OllamaError as e:
        raise MissionGenerationError(
            f"ollama call failed during repair retry: {e}"
        ) from e

    content = _try_parse(raw2)
    if content is not None:
        return content

    raise MissionGenerationError(
        "ollama returned invalid mission shape after repair retry; "
        f"last raw output (truncated): {raw2[:300]!r}"
    )


_SIGNOFF_TITLES: dict[str, str] = {
    "agency": "Director Zero",
    "pulp": "Professor Zero",
    "guild": "Guildmaster Zero",
}


def _ensure_signoff(content: MissionContent, *, style: str) -> MissionContent:
    """Guarantee the briefing ends with the correct '— <Title> Zero' sign-off.

    The prompt asks the model to sign off, but a 13B model misses this rule
    in roughly 1-of-3 generations on our hardware. Rather than burn another
    25s repair-retry round trip on a stylistic fix-up, we patch the text in
    code: if the expected sign-off is missing, append it. The 2200-char cap
    is respected by trimming the body first if necessary.

    Wrong-title sign-offs (e.g. Guild output signed by Director Zero) are
    left in place — that's rare and the auto-append would produce a weird
    double sign-off. Logged as a known minor edge case rather than fixed.
    """
    title = _SIGNOFF_TITLES.get(style)
    if title is None:
        return content
    expected = f"— {title}"
    if expected in content.briefing_text:
        return content

    suffix = f"\n\n{expected}"
    # MissionContent caps briefing_text at 2200 chars; reserve room for the suffix.
    max_body = 2200 - len(suffix)
    body = content.briefing_text[:max_body].rstrip()
    return content.model_copy(update={"briefing_text": body + suffix})


def _try_parse(raw: str) -> MissionContent | None:
    """Strip fences, parse JSON, Pydantic-validate. Returns None on any failure
    so the caller can decide whether to retry or surface."""
    cleaned = _strip_markdown_fences(raw)
    try:
        return MissionContent.model_validate_json(cleaned)
    except ValidationError:
        return None
    except (json.JSONDecodeError, ValueError):
        return None


async def _library_lookup(
    db: AsyncSession, *, place_id: uuid.UUID, style: str
) -> Mission | None:
    """Return the best-loved still-active mission for this place+style, if any.

    Excludes `repeat_visit=True` rows — those have follow-up framing
    ('secondary sweep' etc.) that would be jarring for a first-time visitor.
    A first-visit library hit is shared across users; a repeat-visit briefing
    is per-user-context and dies with its single mission row.
    """
    stmt = (
        select(Mission)
        .where(
            Mission.place_id == place_id,
            Mission.adventure_style == style,
            Mission.status == MissionStatus.ACTIVE.value,
            Mission.mission_thumbs_down < 3,
            Mission.repeat_visit.is_(False),
        )
        .order_by(Mission.mission_thumbs_up.desc(), Mission.created_at.asc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()

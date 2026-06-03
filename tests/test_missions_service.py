import json
import uuid

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.models import Mission, Place, User, UserPlaceHistory
from dispatchzero.schemas.missions import MissionContent
from dispatchzero.services.missions import (
    MissionGenerationError,
    _ensure_signoff,
    _strip_markdown_fences,
    _user_has_visited,
    get_or_generate_mission,
)
from dispatchzero.services.mission_prompts import build_mission_prompt


def test_strip_markdown_fences_unwraps_json_block():
    raw = '```json\n{"x": 1}\n```'
    assert _strip_markdown_fences(raw) == '{"x": 1}'


def test_strip_markdown_fences_unwraps_plain_block():
    raw = '```\n{"x": 1}\n```'
    assert _strip_markdown_fences(raw) == '{"x": 1}'


def test_strip_markdown_fences_passes_through_unwrapped_json():
    raw = '{"x": 1}'
    assert _strip_markdown_fences(raw) == '{"x": 1}'


def test_strip_markdown_fences_handles_leading_whitespace():
    raw = '\n\n```json\n{"x": 1}\n```\n'
    assert _strip_markdown_fences(raw) == '{"x": 1}'


# ---------- _ensure_signoff ----------

def _content(briefing: str) -> MissionContent:
    return MissionContent(
        dispatch_summary="Summary.",
        briefing_text=briefing,
        clue=None,
        badge_framing=None,
    )


def test_ensure_signoff_appends_when_missing_agency():
    c = _content("Travel to the target. Be quick.")
    out = _ensure_signoff(c, style="agency")
    assert out.briefing_text.endswith("— Director Zero")


def test_ensure_signoff_appends_when_missing_pulp():
    c = _content("To the church, my friend, swiftly.")
    out = _ensure_signoff(c, style="pulp")
    assert out.briefing_text.endswith("— Professor Zero")


def test_ensure_signoff_appends_when_missing_guild():
    c = _content("Witness the trailhead. Leave no trace.")
    out = _ensure_signoff(c, style="guild")
    assert out.briefing_text.endswith("— Guildmaster Zero")


def test_ensure_signoff_noop_when_already_present():
    """If the model signed off correctly, leave the briefing untouched."""
    c = _content("Travel to the target. Be quick.\n\n— Director Zero")
    out = _ensure_signoff(c, style="agency")
    assert out.briefing_text == c.briefing_text


def test_ensure_signoff_respects_2200_char_cap():
    """If appending would breach the schema cap, trim the body first."""
    long_body = "x" * 2200
    c = _content(long_body)
    out = _ensure_signoff(c, style="guild")
    assert len(out.briefing_text) <= 2200
    assert out.briefing_text.endswith("— Guildmaster Zero")


# ---------- repeat-visit prompt + flow ----------

def test_build_mission_prompt_no_repeat_omits_followup_framing():
    """First-visit briefings shouldn't carry follow-up framing in the prompt
    — would confuse the model into pretending the operative has been there."""
    msgs = build_mission_prompt(
        style="agency", callsign="Solo", place_name="X", place_category="historic",
        place_description=None, repeat_visit=False,
    )
    user_msg = msgs[-1]["content"]
    assert "FOLLOW-UP DISPATCH" not in user_msg
    assert "previously completed" not in user_msg


def test_build_mission_prompt_repeat_includes_followup_framing():
    """Repeat-visit briefings get explicit follow-up framing in the prompt."""
    msgs = build_mission_prompt(
        style="agency", callsign="Solo", place_name="X", place_category="historic",
        place_description=None, repeat_visit=True,
    )
    user_msg = msgs[-1]["content"]
    assert "FOLLOW-UP DISPATCH" in user_msg
    assert "previously completed" in user_msg
    # And the prompt explicitly forbids stating visit count numerically
    assert "numerically" in user_msg


@pytest.mark.asyncio
async def test_user_has_visited_returns_true_after_history_row(db_session):
    user, place = await _make_user_and_place(db_session)
    assert not await _user_has_visited(db_session, user_id=user.id, place_id=place.id)

    db_session.add(UserPlaceHistory(user_id=user.id, place_id=place.id))
    await db_session.commit()

    assert await _user_has_visited(db_session, user_id=user.id, place_id=place.id)


@pytest.mark.asyncio
async def test_repeat_visit_bypasses_library_and_marks_mission(db_session, monkeypatch):
    """User has prior history → library cache MUST be bypassed (force fresh
    generation) AND the resulting mission row gets repeat_visit=True so it
    doesn't leak into other users' first-visit library lookups."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    # Seed a library mission for this place+style — would normally be returned
    cached_payload = {
        "dispatch_summary": "CACHED summary.",
        "briefing_text": "CACHED briefing.",
        "clue": None, "badge_framing": None,
    }
    cached = Mission(
        place_id=place.id, adventure_style="agency",
        dispatch_summary=cached_payload["dispatch_summary"],
        briefing_text=cached_payload["briefing_text"],
        repeat_visit=False,
    )
    db_session.add(cached)

    # Mark the user as having previously visited this place
    db_session.add(UserPlaceHistory(user_id=user.id, place_id=place.id))
    await db_session.commit()

    fresh_payload = {
        "dispatch_summary": "FRESH follow-up summary.",
        "briefing_text": "FRESH follow-up briefing.",
        "clue": None, "badge_framing": None,
    }
    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response(fresh_payload))
        )
        mission = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="agency",
        )

    # We got the FRESH one, not the cached one
    assert "FRESH" in mission.dispatch_summary
    assert mission.repeat_visit is True
    # The cached one is still in the DB but wasn't returned
    rows = (
        await db_session.execute(
            select(Mission).where(Mission.place_id == place.id)
        )
    ).scalars().all()
    assert len(rows) == 2  # cached + fresh


@pytest.mark.asyncio
async def test_first_visit_uses_library_hit_when_available(db_session, monkeypatch):
    """No prior history → library hit returned without an LLM call. Mirror
    of the pre-existing test, but explicit about the repeat-visit invariant
    not breaking the cache path for new users."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    cached = Mission(
        place_id=place.id, adventure_style="agency",
        dispatch_summary="Hello world.",
        briefing_text="Body.",
        repeat_visit=False,
    )
    db_session.add(cached)
    await db_session.commit()

    # No respx mock — if the code calls out to Ollama, the test fails
    mission = await get_or_generate_mission(
        db=db_session, user=user, place_id=place.id, adventure_style="agency",
    )
    assert mission.id == cached.id
    assert mission.repeat_visit is False


@pytest.mark.asyncio
async def test_library_lookup_skips_repeat_visit_missions(db_session, monkeypatch):
    """A first-time visitor must NOT receive a follow-up briefing from the
    library cache. If only repeat_visit rows exist for a place, the system
    generates fresh for the new user (with repeat_visit=False)."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    # Only a repeat-visit mission exists for this place — leftover from
    # some other user's follow-up dispatch
    leftover = Mission(
        place_id=place.id, adventure_style="agency",
        dispatch_summary="The file is reopened.",
        briefing_text="Back again.",
        repeat_visit=True,
    )
    db_session.add(leftover)
    await db_session.commit()

    fresh_payload = {
        "dispatch_summary": "First-visit summary.",
        "briefing_text": "First-visit briefing.",
        "clue": None, "badge_framing": None,
    }
    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response(fresh_payload))
        )
        mission = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="agency",
        )
    assert mission.id != leftover.id
    assert mission.repeat_visit is False
    assert "First-visit" in mission.dispatch_summary


async def _make_user_and_place(db: AsyncSession) -> tuple[User, Place]:
    user = User(
        callsign="Trevor",
        callsign_lower="trevor",
        password_hash="x",
        adventure_style="agency",
    )
    place = Place(
        osm_type="node",
        osm_id=1,
        name="Test Sculpture",
        category="sculpture",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)",
        tags={},
        description="A test piece.",
    )
    db.add_all([user, place])
    await db.commit()
    await db.refresh(user)
    await db.refresh(place)
    return user, place


def _ollama_response(payload: dict) -> dict:
    return {
        "id": "chatcmpl-test",
        "model": "gpt-oss:120b",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(payload)},
                "finish_reason": "stop",
            }
        ],
    }


@pytest.mark.asyncio
async def test_generate_calls_ollama_and_persists_mission(db_session, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_MODEL", "gpt-oss:120b")  # pin to default so assertion is stable
    user, place = await _make_user_and_place(db_session)

    payload = {
        "dispatch_summary": "Document the Test Sculpture.",
        "briefing_text": "Travel to the Test Sculpture and capture proof of its existence.",
        "clue": "Look for the brass plaque at the base.",
        "badge_framing": "First Sculpture Documented",
    }
    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response(payload))
        )
        mission = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="agency"
        )

    assert mission.dispatch_summary == "Document the Test Sculpture."
    assert mission.adventure_style == "agency"
    assert mission.ai_model == "gpt-oss:120b"
    rows = (await db_session.execute(select(Mission))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_library_hit_does_not_call_ollama(db_session, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    payload = {
        "dispatch_summary": "First.",
        "briefing_text": "Body.",
        "clue": None,
        "badge_framing": None,
    }
    with respx.mock:
        route = respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response(payload))
        )
        m1 = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="agency"
        )
        m2 = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="agency"
        )
    assert m1.id == m2.id
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_different_styles_generate_different_missions(db_session, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    payload = {
        "dispatch_summary": "X",
        "briefing_text": "Y",
        "clue": None,
        "badge_framing": None,
    }
    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response(payload))
        )
        m1 = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="agency"
        )
        m2 = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="pulp"
        )
    assert m1.id != m2.id


@pytest.mark.asyncio
async def test_unknown_place_raises(db_session):
    user = User(
        callsign="X", callsign_lower="x", password_hash="x", adventure_style="agency",
    )
    db_session.add(user)
    await db_session.commit()

    with pytest.raises(MissionGenerationError, match="place"):
        await get_or_generate_mission(
            db=db_session, user=user, place_id=uuid.uuid4(), adventure_style="agency"
        )


@pytest.mark.asyncio
async def test_malformed_ollama_json_raises_after_repair_retry(db_session, monkeypatch):
    """Two failures in a row (initial + repair retry) surface an error.
    The retry path is exercised — respx.mock returns the wrong-shape payload
    BOTH times, so we expect MissionGenerationError and 2 calls (not 1)."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    with respx.mock:
        route = respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response({"wrong_shape": True}))
        )
        with pytest.raises(MissionGenerationError, match="repair retry"):
            await get_or_generate_mission(
                db=db_session, user=user, place_id=place.id, adventure_style="agency"
            )
    assert route.call_count == 2, "should attempt repair before giving up"


@pytest.mark.asyncio
async def test_repair_retry_recovers_from_first_bad_output(db_session, monkeypatch):
    """When the first generation is invalid but the repair retry produces a
    valid MissionContent, the mission persists normally — no error surfaced.
    This is the path that turns 'flaky 13B model' into 'reliable production
    behavior'."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    good_payload = {
        "dispatch_summary": "Document the Test Sculpture.",
        "briefing_text": "Travel to the Test Sculpture and capture proof.",
        "clue": None,
        "badge_framing": None,
    }
    with respx.mock:
        route = respx.post("https://ollama.com/v1/chat/completions").mock(
            side_effect=[
                # First attempt: invalid shape
                httpx.Response(200, json=_ollama_response({"wrong_shape": True})),
                # Repair retry: valid
                httpx.Response(200, json=_ollama_response(good_payload)),
            ]
        )
        mission = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="agency"
        )
    assert mission.dispatch_summary == "Document the Test Sculpture."
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_default_style_falls_back_to_user_profile(db_session, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)
    payload = {
        "dispatch_summary": "A",
        "briefing_text": "B",
        "clue": None,
        "badge_framing": None,
    }
    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response(payload))
        )
        mission = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style=None
        )
    assert mission.adventure_style == "agency"

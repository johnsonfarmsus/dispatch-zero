import json
import uuid

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.models import Mission, Place, User
from dispatchzero.services.missions import (
    MissionGenerationError,
    get_or_generate_mission,
)


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
async def test_malformed_ollama_json_raises(db_session, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response({"wrong_shape": True}))
        )
        with pytest.raises(MissionGenerationError):
            await get_or_generate_mission(
                db=db_session, user=user, place_id=place.id, adventure_style="agency"
            )


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

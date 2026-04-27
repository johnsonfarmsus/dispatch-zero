import json
import uuid

import httpx
import pytest
import respx

from dispatchzero.models import Place

SIGNUP = {
    "callsign": "Hunter",
    "password": "long-enough-password",
    "adventure_style": "agency",
}


def _ollama_payload() -> dict:
    return {
        "id": "chatcmpl-test",
        "model": "gpt-oss:120b",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "dispatch_summary": "A two-line preview.",
                            "briefing_text": "The full briefing body.",
                            "clue": "Look up.",
                            "badge_framing": "First Mural",
                        }
                    ),
                },
                "finish_reason": "stop",
            }
        ],
    }


async def _make_place(db_session) -> Place:
    place = Place(
        osm_type="node",
        osm_id=42,
        name="Test Mural",
        category="mural",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)",
        tags={},
    )
    db_session.add(place)
    await db_session.commit()
    await db_session.refresh(place)
    return place


@pytest.mark.asyncio
async def test_generate_requires_auth(client, db_session, redis_client):
    client.cookies.clear()
    r = await client.post("/missions/generate", json={"place_id": str(uuid.uuid4())})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_generate_returns_mission(client, db_session, redis_client, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    await client.post("/auth/signup", json=SIGNUP)
    place = await _make_place(db_session)

    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )
        r = await client.post("/missions/generate", json={"place_id": str(place.id)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dispatch_summary"] == "A two-line preview."
    assert body["adventure_style"] == "agency"


@pytest.mark.asyncio
async def test_generate_returns_library_hit_on_repeat_call(
    client, db_session, redis_client, monkeypatch
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    await client.post("/auth/signup", json=SIGNUP)
    place = await _make_place(db_session)

    with respx.mock:
        route = respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )
        r1 = await client.post("/missions/generate", json={"place_id": str(place.id)})
        r2 = await client.post("/missions/generate", json={"place_id": str(place.id)})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_get_mission_returns_full_payload_with_nested_place(
    client, db_session, redis_client, monkeypatch
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    await client.post("/auth/signup", json=SIGNUP)
    place = await _make_place(db_session)
    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )
        gen = await client.post("/missions/generate", json={"place_id": str(place.id)})
    mission_id = gen.json()["id"]

    r = await client.get(f"/missions/{mission_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == mission_id
    assert "place" in body
    assert body["place"]["id"] == str(place.id)
    assert body["place"]["name"] == "Test Mural"
    assert body["place"]["category"] == "mural"
    assert abs(body["place"]["lat"] - 47.6605) < 1e-4
    assert abs(body["place"]["lng"] - -117.4198) < 1e-4


@pytest.mark.asyncio
async def test_get_mission_404_for_unknown_id(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP)
    r = await client.get(f"/missions/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_mission_requires_auth(client, db_session, redis_client):
    client.cookies.clear()
    r = await client.get(f"/missions/{uuid.uuid4()}")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_generate_returns_404_for_unknown_place(
    client, db_session, redis_client, monkeypatch
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    await client.post("/auth/signup", json=SIGNUP)

    r = await client.post("/missions/generate", json={"place_id": str(uuid.uuid4())})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_generate_returns_503_when_ollama_unavailable(
    client, db_session, redis_client, monkeypatch
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    await client.post("/auth/signup", json=SIGNUP)
    place = await _make_place(db_session)

    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(503)
        )
        r = await client.post("/missions/generate", json={"place_id": str(place.id)})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_generate_overrides_style_when_provided(
    client, db_session, redis_client, monkeypatch
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    await client.post("/auth/signup", json=SIGNUP)  # user is "agency"
    place = await _make_place(db_session)

    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )
        r = await client.post(
            "/missions/generate",
            json={"place_id": str(place.id), "adventure_style": "pulp"},
        )
    assert r.status_code == 200
    assert r.json()["adventure_style"] == "pulp"

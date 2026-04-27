import json
from datetime import datetime

import httpx
import pytest
import respx

from dispatchzero.models import Mission, Place
from dispatchzero.services.photo import make_test_jpeg

SIGNUP = {
    "callsign": "Hunter",
    "password": "long-enough-password",
    "adventure_style": "agency",
}


def _ollama_payload() -> dict:
    return {
        "id": "x", "model": "gpt-oss:120b",
        "choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps({
                "dispatch_summary": "Dispatch.", "briefing_text": "Briefing body.",
                "clue": "Hint.", "badge_framing": "Badge",
            })},
        }],
    }


def _overpass_one() -> dict:
    return {"elements": [{
        "type": "node", "id": 9001, "lat": 47.6605, "lon": -117.4198,
        "tags": {"name": "Test Mural", "tourism": "artwork", "artwork_type": "mural"},
    }]}


@pytest.mark.asyncio
async def test_full_flow_request_capture_rate(
    client, db_session, redis_client, tmp_path, monkeypatch,
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_MODEL", "gpt-oss:120b")
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))

    await client.post("/auth/signup", json=SIGNUP)

    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json=_overpass_one())
        )
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )

        # 1) request
        r1 = await client.post("/missions/request", json={
            "lat": 47.6605, "lng": -117.4198, "radius_m": 2000,
        })
        assert r1.status_code == 200, r1.text
        mission = r1.json()
        mission_id = mission["id"]

        # 2) accept
        r2 = await client.post(f"/missions/{mission_id}/accept")
        assert r2.status_code == 204

        # 3) capture
        photo_bytes = make_test_jpeg(captured_at=datetime.utcnow())
        r3 = await client.post(
            f"/missions/{mission_id}/capture",
            files={"photo": ("p.jpg", photo_bytes, "image/jpeg")},
            data={"lat": "47.6605", "lng": "-117.4198", "accuracy_m": "8.0"},
        )
        assert r3.status_code == 200, r3.text
        debrief = r3.json()
        assert debrief["completion"]["verified"] is True
        assert debrief["user_completions_count"] == 1
        assert debrief["user_missions_this_week"] == 1
        completion_id = debrief["completion"]["id"]

        # 4) rate
        r4 = await client.post(
            f"/missions/completions/{completion_id}/rate",
            json={"location_rating": "up", "mission_rating": "up"},
        )
        assert r4.status_code == 200


@pytest.mark.asyncio
async def test_request_falls_through_overpass_timeout_to_wikipedia(
    client, db_session, redis_client, tmp_path, monkeypatch,
):
    """If Overpass times out, /missions/request should escalate to Wikipedia
    rather than 500ing. Models the rural-area path where OSM is also empty."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_MODEL", "gpt-oss:120b")
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))

    await client.post("/auth/signup", json=SIGNUP)

    wp_geo = {"query": {"geosearch": [
        {"pageid": 555, "title": "Harrington Opera House", "lat": 47.4810, "lon": -118.2540},
    ]}}
    wp_extracts = {"query": {"pages": {"555": {
        "pageid": 555, "extract": "The Harrington Opera House is a historic building.",
    }}}}

    with respx.mock:
        # All Overpass POSTs time out — every overpass tier should be skipped.
        respx.post("https://overpass-api.de/api/interpreter").mock(
            side_effect=httpx.ReadTimeout("overpass timed out")
        )
        # Wikipedia returns one named, non-populated-place landmark.
        respx.get("https://en.wikipedia.org/w/api.php").mock(
            side_effect=[
                httpx.Response(200, json=wp_geo),
                httpx.Response(200, json=wp_extracts),
            ]
        )
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )

        r = await client.post("/missions/request", json={
            "lat": 47.4808, "lng": -118.2547, "radius_m": 2000,
        })

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["place"]["name"] == "Harrington Opera House"


@pytest.mark.asyncio
async def test_capture_returns_422_for_out_of_radius(
    client, db_session, redis_client, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    await client.post("/auth/signup", json=SIGNUP)

    place = Place(
        osm_type="node", osm_id=1, name="X", category="sculpture",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)", tags={},
    )
    db_session.add(place); await db_session.commit(); await db_session.refresh(place)
    mission = Mission(
        place_id=place.id, adventure_style="agency",
        dispatch_summary="x", briefing_text="y",
    )
    db_session.add(mission); await db_session.commit(); await db_session.refresh(mission)

    photo_bytes = make_test_jpeg(captured_at=datetime.utcnow())
    r = await client.post(
        f"/missions/{mission.id}/capture",
        files={"photo": ("p.jpg", photo_bytes, "image/jpeg")},
        data={"lat": "47.6900", "lng": "-117.4000", "accuracy_m": "8.0"},
    )
    assert r.status_code == 422
    assert "proof" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_capture_requires_auth(client, db_session, redis_client):
    client.cookies.clear()
    photo_bytes = make_test_jpeg(captured_at=datetime.utcnow())
    r = await client.post(
        "/missions/00000000-0000-0000-0000-000000000000/capture",
        files={"photo": ("p.jpg", photo_bytes, "image/jpeg")},
        data={"lat": "0", "lng": "0"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_missions_request_rate_limit_kicks_in(
    client, db_session, redis_client, monkeypatch,
):
    """After hitting the cap, /missions/request returns 429."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_MODEL", "gpt-oss:120b")
    monkeypatch.setenv("RATE_LIMIT_MISSION_REQUEST_PER_DAY", "2")

    await client.post("/auth/signup", json=SIGNUP)

    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json=_overpass_one())
        )
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )

        for _ in range(2):
            r = await client.post("/missions/request", json={
                "lat": 47.6605, "lng": -117.4198, "radius_m": 2000,
            })
            assert r.status_code == 200, r.text

        r = await client.post("/missions/request", json={
            "lat": 47.6605, "lng": -117.4198, "radius_m": 2000,
        })
    assert r.status_code == 429, r.text
    assert "Retry-After" in r.headers


@pytest.mark.asyncio
async def test_rate_rejects_someone_elses_completion(
    client, db_session, redis_client, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    await client.post("/auth/signup", json={**SIGNUP, "callsign": "AgentA"})
    place = Place(
        osm_type="node", osm_id=2, name="Y", category="sculpture",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)", tags={},
    )
    db_session.add(place); await db_session.commit()
    from sqlalchemy import select
    from dispatchzero.models import Completion, User
    user_a = (
        await db_session.execute(select(User).where(User.callsign_lower == "agenta"))
    ).scalar_one()
    mission = Mission(
        place_id=place.id, adventure_style="agency",
        dispatch_summary="x", briefing_text="y",
    )
    db_session.add(mission); await db_session.commit(); await db_session.refresh(mission)
    completion = Completion(
        user_id=user_a.id, mission_id=mission.id, place_id=place.id,
        capture_lat=47.6605, capture_lng=-117.4198, verified=True,
    )
    db_session.add(completion); await db_session.commit(); await db_session.refresh(completion)

    client.cookies.clear()
    await client.post("/auth/signup", json={**SIGNUP, "callsign": "AgentB"})
    r = await client.post(
        f"/missions/completions/{completion.id}/rate",
        json={"location_rating": "down"},
    )
    assert r.status_code == 403

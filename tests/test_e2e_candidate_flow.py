"""End-to-end test of the modern candidate flow — the exact path the UI walks.

The older /missions/request flow has its own E2E (test_missions_flow_routes),
but the frontend has since moved to choose-then-generate:

    home.js            -> POST /missions/candidates          (discovery only)
    dispatch-choose.js -> POST /missions/candidates/accept   (one generation)
    transit/capture    -> POST /missions/{id}/accept, /capture
    debrief/rate       -> POST /missions/completions/{id}/rate
    share              -> GET  /c/{token}, card.jpg

This test walks that entire chain against real DB + Redis with only the
external HTTP surfaces (Overpass, Ollama) mocked. If a route contract drifts
from what the screens send, this is the test that catches it.
"""
import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from dispatchzero.services.photo import make_test_jpeg

SIGNUP = {
    "callsign": "PathWalker",
    "password": "long-enough-password",
    "adventure_style": "agency",
}

# Two distinct places so the "choose" step is a real choice.
_OVERPASS_TWO = {
    "elements": [
        {
            "type": "node", "id": 9101, "lat": 47.6605, "lon": -117.4198,
            "tags": {"name": "Riverfront Mural", "tourism": "artwork",
                     "artwork_type": "mural"},
        },
        {
            "type": "node", "id": 9102, "lat": 47.6640, "lon": -117.4260,
            "tags": {"name": "Pioneer Statue", "tourism": "artwork",
                     "artwork_type": "statue"},
        },
    ]
}


def _ollama_payload() -> dict:
    return {
        "id": "x", "model": "olmo2:13b",
        "choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps({
                "dispatch_summary": "Proceed to the riverfront, quietly.",
                "briefing_text": "The mural on the riverfront wall is the mark. "
                                 "Document it and withdraw without ceremony.",
                "clue": "Face the water.",
                "badge_framing": "Field Documentation",
                "teaser": "A wall that remembers.",
            })},
        }],
    }


@pytest.mark.asyncio
async def test_e2e_candidate_choose_generate_capture_share(
    client, db_session, redis_client, tmp_path, monkeypatch,
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))

    r = await client.post("/auth/signup", json=SIGNUP)
    assert r.status_code == 201, r.text

    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json=_OVERPASS_TWO)
        )
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )
        # Wikipedia/Wikidata enrichment is best-effort; empty results keep the
        # discovery tiers honest without inventing content.
        respx.get(url__regex=r"https://en\.wikipedia\.org/.*").mock(
            return_value=httpx.Response(200, json={"query": {"geosearch": []}})
        )
        respx.get(url__regex=r"https://www\.wikidata\.org/.*").mock(
            return_value=httpx.Response(200, json={"entities": {}})
        )
        respx.get(url__regex=r"https://nominatim\.openstreetmap\.org/.*").mock(
            return_value=httpx.Response(200, json=[])
        )

        # 1) Discovery — no generation happens here.
        r1 = await client.post("/missions/candidates", json={
            "lat": 47.6610, "lng": -117.4200, "radius_m": 2000,
        })
        assert r1.status_code == 200, r1.text
        slate = r1.json()
        assert len(slate["candidates"]) >= 2
        for c in slate["candidates"]:
            assert c["place_id"]
            assert c["distance_m"] >= 0
            assert c["bearing_compass"]

        # 2) Choose the mural and accept -> the single generation call.
        chosen = next(
            c for c in slate["candidates"] if c["place_name"] == "Riverfront Mural"
        )
        r2 = await client.post("/missions/candidates/accept", json={
            "place_id": chosen["place_id"],
        })
        assert r2.status_code == 200, r2.text
        mission = r2.json()
        assert mission["adventure_style"] == "agency"
        assert "riverfront" in mission["briefing_text"].lower()
        # Sign-off is code-appended, never model-produced.
        assert mission["briefing_text"].rstrip().endswith("Director Zero")
        # The primary model wrote this brief (no fallback engaged).
        assert mission["ai_model"] == "olmo2:13b"

        # 3) Activate.
        r3 = await client.post(f"/missions/{mission['id']}/accept")
        assert r3.status_code == 204

        # 4) Capture in radius with a fresh photo.
        photo = make_test_jpeg(captured_at=datetime.now(timezone.utc))
        r4 = await client.post(
            f"/missions/{mission['id']}/capture",
            files={"photo": ("p.jpg", photo, "image/jpeg")},
            data={"lat": "47.6605", "lng": "-117.4198", "accuracy_m": "8.0"},
        )
        assert r4.status_code == 200, r4.text
        debrief = r4.json()
        assert debrief["completion"]["verified"] is True
        assert debrief["user_completions_count"] == 1
        completion = debrief["completion"]

        # 5) Rate both axes.
        r5 = await client.post(
            f"/missions/completions/{completion['id']}/rate",
            json={"location_rating": "up", "mission_rating": "up"},
        )
        assert r5.status_code == 200, r5.text

        # 6) Mission card renders as a real JPEG.
        r6 = await client.get(f"/missions/completions/{completion['id']}/card.jpg")
        assert r6.status_code == 200, r6.text
        assert r6.headers["content-type"] == "image/jpeg"
        assert r6.content[:3] == b"\xff\xd8\xff"

    # 7) The share page is public: same URLs must work with NO session.
    client.cookies.clear()
    r7 = await client.get(f"/c/{completion['share_token']}")
    assert r7.status_code == 200
    assert "text/html" in r7.headers["content-type"]
    # The public page must not leak coordinates (privacy invariant).
    assert "47.66" not in r7.text
    assert "-117.4" not in r7.text

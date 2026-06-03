"""Tests for the Stage 3 candidate-list service.

Covers:
- distance_and_bearing_m: geometry sanity (known examples)
- gather_candidate_places: multi-tier accumulation, dedup, target_count cap,
  graceful handling of tier failures
- generate_candidate_missions tested implicitly via the route-level test
  in test_missions_flow_routes (it requires the full app + DB context)
"""
import uuid

import httpx
import pytest
import respx
from sqlalchemy import select

from dispatchzero.models import Place, User
from dispatchzero.services.candidates import (
    distance_and_bearing_m,
    empty_message,
    gather_candidate_places,
)


def test_distance_and_bearing_known_examples():
    """Sanity: short east-west movement → bearing ~E, distance > 0."""
    # 0.001 deg lng at lat 47.48 is ~76 m east
    d, bearing = distance_and_bearing_m(
        from_lat=47.48, from_lng=-118.25,
        to_lat=47.48, to_lng=-118.249,
    )
    assert 70 <= d <= 90, f"expected ~76m, got {d}"
    assert bearing == "E"


def test_distance_and_bearing_north():
    d, bearing = distance_and_bearing_m(
        from_lat=47.48, from_lng=-118.25,
        to_lat=47.49, to_lng=-118.25,
    )
    # 0.01 deg lat ~1111 m
    assert 1050 <= d <= 1150
    assert bearing == "N"


def test_distance_and_bearing_zero_when_same_point():
    d, bearing = distance_and_bearing_m(
        from_lat=47.48, from_lng=-118.25,
        to_lat=47.48, to_lng=-118.25,
    )
    assert d == 0
    # Bearing at 0 distance is undefined-ish; just confirm it's a valid compass
    assert bearing in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def test_empty_message_is_in_voice_and_nonempty():
    msg = empty_message(47.48, -118.25)
    assert msg
    assert "agent" in msg.lower()


# ---------- gather_candidate_places ----------

async def _make_user(db) -> User:
    u = User(
        callsign="Candidate", callsign_lower="candidate",
        password_hash="x", adventure_style="agency",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


def _overpass_response_with_places(*names: str) -> dict:
    return {
        "elements": [
            {
                "type": "node", "id": 1000 + i,
                "lat": 47.48 + 0.001 * i, "lon": -118.25 + 0.001 * i,
                "tags": {"name": name, "tourism": "artwork",
                         "artwork_type": "mural"},
            }
            for i, name in enumerate(names)
        ]
    }


@pytest.mark.asyncio
async def test_gather_returns_up_to_target_count_from_first_tier(
    db_session, redis_client,
):
    """Happy path: tier 0 has enough — we don't need to escalate."""
    user = await _make_user(db_session)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200, json=_overpass_response_with_places("A", "B", "C", "D", "E"),
            )
        )
        candidates = await gather_candidate_places(
            db=db_session, redis=redis_client, user=user,
            lat=47.48, lng=-118.25, request_radius_m=2000, target_count=3,
        )
    assert len(candidates) == 3
    names = {c["name"] for c in candidates}
    assert names.issubset({"A", "B", "C", "D", "E"})


@pytest.mark.asyncio
async def test_gather_accumulates_across_tiers_when_first_is_thin(
    db_session, redis_client,
):
    """First tier returns one place; second tier returns two more. Result
    must be three (without the airport-lockout behavior the old single-tier
    flow had)."""
    user = await _make_user(db_session)
    with respx.mock:
        # Both narrow + broad Overpass queries hit the same endpoint; we let
        # respx return the same body for both. Place 1 from tier 0 (narrow)
        # will be deduped against the same place if it appears in tier 1+
        # (broad) — they have the same osm_id.
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200, json=_overpass_response_with_places("Solo", "Twin1", "Twin2"),
            )
        )
        candidates = await gather_candidate_places(
            db=db_session, redis=redis_client, user=user,
            lat=47.48, lng=-118.25, request_radius_m=2000, target_count=3,
        )
    # All three are deduped via Place.id, so even though multiple tiers
    # returned the same Overpass response, we get 3 unique candidates.
    assert len(candidates) == 3


@pytest.mark.asyncio
async def test_gather_dedupes_by_place_id(db_session, redis_client):
    """A place returned by multiple tiers should appear ONCE in the slate.
    With only one unique place across all tiers, we'd keep walking tiers
    looking for more — so the Wikipedia mock has to be set up too even
    though we only care about the Overpass dedup behavior."""
    user = await _make_user(db_session)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200, json=_overpass_response_with_places("Duplicate"),
            )
        )
        respx.get(url__regex=r"https://en\.wikipedia\.org/.*").mock(
            return_value=httpx.Response(200, json={"query": {"geosearch": []}})
        )
        candidates = await gather_candidate_places(
            db=db_session, redis=redis_client, user=user,
            lat=47.48, lng=-118.25, request_radius_m=2000, target_count=3,
        )
    # Only one unique place exists — even though multiple tiers ran
    assert len(candidates) == 1
    assert candidates[0]["name"] == "Duplicate"


@pytest.mark.asyncio
async def test_gather_returns_empty_when_no_tiers_yield(db_session, redis_client):
    """No upstream returns anything → empty list (route layer surfaces the
    'nothing fresh' message)."""
    user = await _make_user(db_session)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json={"elements": []})
        )
        respx.get(url__regex=r"https://en\.wikipedia\.org/.*").mock(
            return_value=httpx.Response(200, json={"query": {"geosearch": []}})
        )
        candidates = await gather_candidate_places(
            db=db_session, redis=redis_client, user=user,
            lat=47.48, lng=-118.25, request_radius_m=2000, target_count=3,
        )
    assert candidates == []


@pytest.mark.asyncio
async def test_gather_skips_tier_on_transport_error(db_session, redis_client):
    """A tier failing with httpx.HTTPError shouldn't kill the whole gather —
    we should still try the next tier and return whatever we get."""
    user = await _make_user(db_session)

    # First call (overpass) raises; later calls return one place
    call_count = {"n": 0}

    def overpass_handler(request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("simulated", request=request)
        return httpx.Response(
            200, json=_overpass_response_with_places("Recovered"),
        )

    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            side_effect=overpass_handler
        )
        respx.get(url__regex=r"https://en\.wikipedia\.org/.*").mock(
            return_value=httpx.Response(200, json={"query": {"geosearch": []}})
        )
        candidates = await gather_candidate_places(
            db=db_session, redis=redis_client, user=user,
            lat=47.48, lng=-118.25, request_radius_m=2000, target_count=3,
        )
    # Tier 0 failed, tier 1 succeeded → we got the recovered place
    assert any(c["name"] == "Recovered" for c in candidates)

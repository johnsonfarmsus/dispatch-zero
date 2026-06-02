"""Tests for the local-DB discovery tier (PostGIS radius query).

Verifies that places stored in the DB are returned via the 'local' source
within radius, that distant places are excluded, that the 90-day re-entry
filter still applies, and that the safety filter still drops school-named
rows even if they slip into the DB somehow.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from dispatchzero.models import Place, User, UserPlaceHistory
from dispatchzero.services.discovery import discover_nearby


async def _make_user(db_session) -> User:
    user = User(
        callsign="LocalTester", callsign_lower="localtester",
        password_hash="x", adventure_style="agency",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_gnis_place(db_session, *, name: str, lat: float, lng: float,
                             osm_id: int = 1, category: str = "church") -> Place:
    place = Place(
        id=uuid.uuid4(),
        osm_type="gnis", osm_id=osm_id, name=name, category=category,
        coordinates=f"SRID=4326;POINT({lng} {lat})",
        tags={"source": "gnis", "county": "Lincoln"},
    )
    db_session.add(place)
    await db_session.commit()
    await db_session.refresh(place)
    return place


@pytest.mark.asyncio
async def test_local_tier_returns_nearby_gnis_place(db_session, redis_client):
    user = await _make_user(db_session)
    await _seed_gnis_place(db_session, name="Harrington Trinity Church",
                            lat=47.481, lng=-118.255, osm_id=10001)

    results = await discover_nearby(
        db=db_session, redis=redis_client, user=user,
        lat=47.4808, lng=-118.2547, radius_m=2000, limit=10,
        source="local",
    )
    assert len(results) == 1
    assert results[0]["name"] == "Harrington Trinity Church"


@pytest.mark.asyncio
async def test_local_tier_excludes_places_outside_radius(db_session, redis_client):
    user = await _make_user(db_session)
    # Far away (Seattle-ish), well outside a 5km query from Harrington
    await _seed_gnis_place(db_session, name="St Mark's Cathedral",
                            lat=47.625, lng=-122.323, osm_id=10002)

    results = await discover_nearby(
        db=db_session, redis=redis_client, user=user,
        lat=47.4808, lng=-118.2547, radius_m=5000, limit=10,
        source="local",
    )
    assert results == []


@pytest.mark.asyncio
async def test_local_tier_respects_90_day_re_entry_filter(db_session, redis_client):
    user = await _make_user(db_session)
    place = await _seed_gnis_place(
        db_session, name="St Joseph", lat=47.481, lng=-118.255, osm_id=10003,
    )
    # User completed this place 30 days ago — still inside the 90-day window
    db_session.add(UserPlaceHistory(
        id=uuid.uuid4(), user_id=user.id, place_id=place.id,
        last_completed_at=datetime.now(timezone.utc) - timedelta(days=30),
    ))
    await db_session.commit()

    results = await discover_nearby(
        db=db_session, redis=redis_client, user=user,
        lat=47.4808, lng=-118.2547, radius_m=2000, limit=10,
        source="local",
    )
    assert results == []


@pytest.mark.asyncio
async def test_local_tier_filters_school_named_rows(db_session, redis_client):
    """Defense in depth: even if a school-named row landed in the DB somehow,
    eligibility filter must drop it."""
    user = await _make_user(db_session)
    await _seed_gnis_place(db_session, name="Lincoln Elementary School",
                            lat=47.481, lng=-118.255, osm_id=10004)
    await _seed_gnis_place(db_session, name="Lincoln Heritage Chapel",
                            lat=47.482, lng=-118.256, osm_id=10005)

    results = await discover_nearby(
        db=db_session, redis=redis_client, user=user,
        lat=47.4808, lng=-118.2547, radius_m=2000, limit=10,
        source="local",
    )
    names = [r["name"] for r in results]
    assert names == ["Lincoln Heritage Chapel"]

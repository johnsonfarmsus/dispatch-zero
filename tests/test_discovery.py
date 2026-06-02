from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from sqlalchemy import select

from dispatchzero.models import Place, User, UserPlaceHistory
from dispatchzero.services.discovery import discover_nearby


def _overpass_response_with(*pairs: tuple[int, str, str]) -> dict:
    """Build a fake Overpass response: (osm_id, name, artwork_type) tuples."""
    return {
        "elements": [
            {
                "type": "node",
                "id": osm_id,
                "lat": 37.7749 + 0.001 * i,
                "lon": -122.4194 + 0.001 * i,
                "tags": {"name": name, "tourism": "artwork", "artwork_type": atype},
            }
            for i, (osm_id, name, atype) in enumerate(pairs)
        ]
    }


async def _make_user(db_session) -> User:
    user = User(
        callsign="Tester",
        callsign_lower="tester",
        password_hash="x",
        adventure_style="agency",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_discover_returns_results_and_persists_places(db_session, redis_client):
    user = await _make_user(db_session)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200,
                json=_overpass_response_with(
                    (1, "Mural One", "mural"),
                    (2, "Mural Two", "mural"),
                ),
            )
        )
        results = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )

    assert len(results) == 2
    rows = (await db_session.execute(select(Place))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_discover_filters_recently_completed_places(db_session, redis_client):
    user = await _make_user(db_session)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200, json=_overpass_response_with((1, "Already Done", "mural"))
            )
        )
        first = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )
        assert len(first) == 1

        history = UserPlaceHistory(
            user_id=user.id,
            place_id=first[0]["id"],
            last_completed_at=datetime.now(timezone.utc),
        )
        db_session.add(history)
        await db_session.commit()

        second = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )
        assert len(second) == 0


@pytest.mark.asyncio
async def test_discover_includes_old_completion_after_90_days(db_session, redis_client):
    user = await _make_user(db_session)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200, json=_overpass_response_with((1, "Long Ago", "mural"))
            )
        )
        first = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )
        history = UserPlaceHistory(
            user_id=user.id,
            place_id=first[0]["id"],
            last_completed_at=datetime.now(timezone.utc) - timedelta(days=91),
        )
        db_session.add(history)
        await db_session.commit()

        second = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )
        assert len(second) == 1


@pytest.mark.asyncio
async def test_discover_filters_unnamed_places(db_session, redis_client):
    user = await _make_user(db_session)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200,
                json={
                    "elements": [
                        {
                            "type": "node", "id": 1, "lat": 37.78, "lon": -122.41,
                            "tags": {"tourism": "artwork", "artwork_type": "mural"},  # no name
                        },
                        {
                            "type": "node", "id": 2, "lat": 37.79, "lon": -122.42,
                            "tags": {"name": "Has a Name", "tourism": "artwork", "artwork_type": "mural"},
                        },
                    ]
                },
            )
        )
        results = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )
    assert len(results) == 1
    assert results[0]["name"] == "Has a Name"


@pytest.mark.asyncio
async def test_discover_excludes_schools_and_academies(db_session, redis_client):
    """Safety filter: places named 'school', 'academy', etc. must be excluded —
    even if OSM returns them. We do not direct users to facilities full of minors."""
    user = await _make_user(db_session)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200,
                json=_overpass_response_with(
                    (1, "Reardan Elementary School", "mural"),
                    (2, "Wilson Academy", "sculpture"),
                    (3, "St. Mary's Kindergarten", "memorial"),
                    (4, "Daycare Mural", "mural"),
                    (5, "Old Town Mural", "mural"),  # the only legit one
                ),
            )
        )
        results = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )
    names = [r["name"] for r in results]
    assert names == ["Old Town Mural"]


def test_excluded_by_name_predicate():
    """Unit-level coverage of the safety predicate. Substring, case-insensitive."""
    from dispatchzero.services.discovery import _excluded_by_name

    # Hits — should be excluded
    assert _excluded_by_name("Reardan Elementary School")
    assert _excluded_by_name("Wilson Academy")
    assert _excluded_by_name("ST MARY'S KINDERGARTEN")
    assert _excluded_by_name("Sunny Day Daycare")
    assert _excluded_by_name("Tiny Tots Preschool")
    assert _excluded_by_name("Lincoln Elementary")  # without "school" suffix
    # Airport-family exclusions — secured perimeters, no public foot access
    assert _excluded_by_name("Spokane International Airport")
    assert _excluded_by_name("Felts Field Airfield")
    assert _excluded_by_name("Backcountry Airstrip")
    assert _excluded_by_name("Runway 27 Marker")
    assert _excluded_by_name("Terminal B Lobby")
    # Misses — should pass through
    assert not _excluded_by_name("Old Town Mural")
    assert not _excluded_by_name("Riverfront Park")
    assert not _excluded_by_name(None)
    assert not _excluded_by_name("")
    # Acceptable false positive — better to skip a museum than risk pointing
    # someone at a former-schoolhouse-still-being-used-as-a-school
    assert _excluded_by_name("Old Schoolhouse Museum")

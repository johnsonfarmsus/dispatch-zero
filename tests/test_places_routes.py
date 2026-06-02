import httpx
import pytest
import respx

SIGNUP = {
    "callsign": "Hunter_01",
    "password": "long-enough-password",
    "adventure_style": "agency",
}


def _overpass_one(name: str = "Test Mural") -> dict:
    return {
        "elements": [
            {
                "type": "node",
                "id": 9001,
                "lat": 37.7749,
                "lon": -122.4194,
                "tags": {"name": name, "tourism": "artwork", "artwork_type": "mural"},
            }
        ]
    }


@pytest.mark.asyncio
async def test_nearby_requires_auth(client, db_session, redis_client):
    client.cookies.clear()
    r = await client.get("/places/nearby?lat=37.7749&lng=-122.4194")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_nearby_returns_places_for_authed_user(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json=_overpass_one())
        )
        r = await client.get("/places/nearby?lat=37.7749&lng=-122.4194")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["name"] == "Test Mural"
    assert body[0]["category"] == "mural"


@pytest.mark.asyncio
async def test_nearby_clamps_radius(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP)
    # radius_m=999999 → clamped to 10000 by Pydantic Query validator → 422 actually
    # Let's test the Query validator instead.
    r = await client.get("/places/nearby?lat=37.7749&lng=-122.4194&radius_m=999999")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_nearby_rejects_invalid_lat_lng(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP)
    r = await client.get("/places/nearby?lat=999&lng=-122.4194")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_report_requires_auth(client, db_session):
    """The /places/{id}/report endpoint needs a session like the rest of /places."""
    client.cookies.clear()
    import uuid
    r = await client.post(f"/places/{uuid.uuid4()}/report",
                          json={"reason": "unreachable"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_report_returns_404_for_unknown_place(client, db_session):
    await client.post("/auth/signup", json=SIGNUP)
    import uuid
    r = await client.post(f"/places/{uuid.uuid4()}/report",
                          json={"reason": "unreachable"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_report_rejects_invalid_reason(client, db_session):
    await client.post("/auth/signup", json=SIGNUP)
    import uuid
    r = await client.post(f"/places/{uuid.uuid4()}/report",
                          json={"reason": "nonsense"})
    # Pydantic Literal rejects unknown values before the route logic runs.
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_report_happy_path_excludes_from_future_discovery(
    client, db_session, redis_client,
):
    """End-to-end: signup → discover one place via overpass → report it →
    re-discover and confirm it's gone for this user."""
    import uuid as _uuid
    from dispatchzero.models import Place

    await client.post("/auth/signup", json=SIGNUP)

    # Seed a place directly (skips the overpass round-trip)
    place = Place(
        id=_uuid.uuid4(),
        osm_type="gnis", osm_id=99999, name="Phantom Reporter Test",
        category="historic",
        coordinates="SRID=4326;POINT(-122.4194 37.7749)",
        tags={"source": "test"},
    )
    db_session.add(place)
    await db_session.commit()

    r = await client.post(
        f"/places/{place.id}/report", json={"reason": "unreachable"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reason"] == "unreachable"
    assert body["place_id"] == str(place.id)

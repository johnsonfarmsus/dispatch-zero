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

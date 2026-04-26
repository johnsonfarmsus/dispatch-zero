import httpx
import pytest
import respx

from dispatchzero.integrations.nominatim import NominatimClient


@pytest.mark.asyncio
async def test_geocode_returns_lat_lng_on_hit(redis_client):
    client = NominatimClient(redis_client)
    with respx.mock:
        respx.get("https://nominatim.openstreetmap.org/search").mock(
            return_value=httpx.Response(
                200,
                json=[{"lat": "37.7749", "lon": "-122.4194", "display_name": "San Francisco"}],
            )
        )
        result = await client.geocode("San Francisco")
    assert result == {"lat": 37.7749, "lng": -122.4194, "display_name": "San Francisco"}


@pytest.mark.asyncio
async def test_geocode_returns_none_on_no_results(redis_client):
    client = NominatimClient(redis_client)
    with respx.mock:
        respx.get("https://nominatim.openstreetmap.org/search").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await client.geocode("nonsense_query_zzzz")
    assert result is None


@pytest.mark.asyncio
async def test_geocode_caches_response(redis_client):
    client = NominatimClient(redis_client)
    with respx.mock:
        route = respx.get("https://nominatim.openstreetmap.org/search").mock(
            return_value=httpx.Response(
                200,
                json=[{"lat": "1.0", "lon": "2.0", "display_name": "X"}],
            )
        )
        await client.geocode("X")
        await client.geocode("X")
    assert route.call_count == 1  # second call hit cache


@pytest.mark.asyncio
async def test_geocode_user_agent_is_set(redis_client):
    client = NominatimClient(redis_client)
    with respx.mock:
        route = respx.get("https://nominatim.openstreetmap.org/search").mock(
            return_value=httpx.Response(200, json=[])
        )
        await client.geocode("anywhere")
    request = route.calls.last.request
    assert "dispatchzero" in request.headers["User-Agent"].lower()

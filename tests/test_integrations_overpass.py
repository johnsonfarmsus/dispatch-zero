import httpx
import pytest
import respx

from dispatchzero.integrations.overpass import (
    OverpassClient,
    build_query,
)
from dispatchzero.models import PlaceCategory


def test_build_query_includes_all_categories():
    q = build_query(lat=37.7749, lng=-122.4194, radius_m=1000, categories=list(PlaceCategory))
    assert "[out:json]" in q
    assert "around:1000" in q
    assert "37.7749" in q
    assert "-122.4194" in q
    assert "artwork_type" in q
    assert "historic=memorial" in q or 'historic"="memorial' in q
    assert "tourism=viewpoint" in q or 'tourism"="viewpoint' in q


@pytest.mark.asyncio
async def test_query_returns_normalized_places(redis_client):
    fake_response = {
        "elements": [
            {
                "type": "node",
                "id": 12345,
                "lat": 37.78,
                "lon": -122.41,
                "tags": {"name": "Some Mural", "tourism": "artwork", "artwork_type": "mural"},
            },
            {
                "type": "way",
                "id": 67890,
                "center": {"lat": 37.79, "lon": -122.42},
                "tags": {"name": "Old Building", "historic": "building"},
            },
        ]
    }
    client = OverpassClient(redis_client)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json=fake_response)
        )
        results = await client.query_nearby(
            lat=37.7749, lng=-122.4194, radius_m=1000, categories=list(PlaceCategory)
        )
    assert len(results) == 2
    assert results[0].osm_type == "node"
    assert results[0].osm_id == 12345
    assert results[0].name == "Some Mural"
    assert results[0].category == PlaceCategory.MURAL
    assert results[1].osm_type == "way"
    assert results[1].lat == 37.79  # used 'center' for ways
    assert results[1].category == PlaceCategory.HISTORIC


@pytest.mark.asyncio
async def test_query_caches_response(redis_client):
    client = OverpassClient(redis_client)
    with respx.mock:
        route = respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json={"elements": []})
        )
        await client.query_nearby(
            lat=1.0, lng=2.0, radius_m=500, categories=[PlaceCategory.MURAL]
        )
        await client.query_nearby(
            lat=1.0, lng=2.0, radius_m=500, categories=[PlaceCategory.MURAL]
        )
    assert route.call_count == 1

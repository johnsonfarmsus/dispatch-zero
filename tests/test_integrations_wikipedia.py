import httpx
import pytest
import respx

from dispatchzero.integrations.wikipedia import (
    WikipediaClient,
    _looks_like_populated_place,
)


def _geo_response(items):
    return {"query": {"geosearch": items}}


def _extracts_response(pages):
    """pages = {pageid: extract_text}"""
    return {"query": {"pages": {str(k): {"pageid": k, "extract": v} for k, v in pages.items()}}}


# ----- Pure heuristic -----

def test_populated_place_detector_catches_typical_patterns():
    assert _looks_like_populated_place("Harrington is a city in Lincoln County, Washington")
    assert _looks_like_populated_place("Smithville is a town in Texas with a population of 4,000")
    assert _looks_like_populated_place("Maple Grove is an unincorporated community in Minnesota")
    assert _looks_like_populated_place("Lincoln County is a county in eastern Washington")


def test_populated_place_detector_misses_landmarks():
    assert not _looks_like_populated_place(
        "The Harrington Bank Block & Opera House is a historic building in Harrington, Washington"
    )
    assert not _looks_like_populated_place(
        "The Garbage Goat is a sculpture in Riverfront Park, Spokane"
    )
    assert not _looks_like_populated_place("")


# ----- Geosearch + extracts roundtrip -----

@pytest.mark.asyncio
async def test_geosearch_returns_articles_with_extracts(redis_client):
    geo = _geo_response([
        {"pageid": 1, "title": "Harrington Bank Block & Opera House", "lat": 47.481, "lon": -118.254},
        {"pageid": 2, "title": "Some Statue", "lat": 47.482, "lon": -118.255},
    ])
    extracts = _extracts_response({
        1: "The Harrington Bank Block & Opera House is a historic building in eastern Washington.",
        2: "Some Statue is a sculpture commemorating local history.",
    })
    client = WikipediaClient(redis_client)
    with respx.mock:
        respx.get("https://en.wikipedia.org/w/api.php").mock(
            side_effect=[
                httpx.Response(200, json=geo),
                httpx.Response(200, json=extracts),
            ]
        )
        results = await client.geosearch(
            lat=47.481, lng=-118.254, radius_m=5000,
        )
    assert len(results) == 2
    assert results[0].title == "Harrington Bank Block & Opera House"
    assert results[0].extract.startswith("The Harrington Bank")
    assert results[1].pageid == 2


@pytest.mark.asyncio
async def test_geosearch_filters_out_populated_place_articles(redis_client):
    geo = _geo_response([
        {"pageid": 100, "title": "Harrington, Washington", "lat": 47.481, "lon": -118.254},
        {"pageid": 200, "title": "Harrington Opera House", "lat": 47.481, "lon": -118.254},
    ])
    extracts = _extracts_response({
        100: "Harrington is a city in Lincoln County, Washington.",
        200: "The Harrington Opera House is a historic building.",
    })
    client = WikipediaClient(redis_client)
    with respx.mock:
        respx.get("https://en.wikipedia.org/w/api.php").mock(
            side_effect=[
                httpx.Response(200, json=geo),
                httpx.Response(200, json=extracts),
            ]
        )
        results = await client.geosearch(lat=47.481, lng=-118.254, radius_m=5000)
    assert len(results) == 1
    assert results[0].title == "Harrington Opera House"


@pytest.mark.asyncio
async def test_geosearch_returns_empty_on_no_results(redis_client):
    client = WikipediaClient(redis_client)
    with respx.mock:
        respx.get("https://en.wikipedia.org/w/api.php").mock(
            return_value=httpx.Response(200, json=_geo_response([]))
        )
        results = await client.geosearch(lat=0.0, lng=0.0, radius_m=1000)
    assert results == []


@pytest.mark.asyncio
async def test_geosearch_caches_response(redis_client):
    geo = _geo_response([
        {"pageid": 1, "title": "X", "lat": 47.0, "lon": -117.0},
    ])
    extracts = _extracts_response({1: "X is a sculpture."})
    client = WikipediaClient(redis_client)
    with respx.mock:
        route = respx.get("https://en.wikipedia.org/w/api.php").mock(
            side_effect=[
                httpx.Response(200, json=geo),
                httpx.Response(200, json=extracts),
                # Subsequent calls — should NOT be invoked
            ]
        )
        await client.geosearch(lat=47.0, lng=-117.0, radius_m=2000)
        await client.geosearch(lat=47.0, lng=-117.0, radius_m=2000)  # cache hit
    assert route.call_count == 2  # 1 geosearch + 1 extracts the first time, no calls the second

import httpx
import pytest
import respx

from dispatchzero.integrations.wikidata import WikidataClient


@pytest.mark.asyncio
async def test_get_description_returns_english_string(redis_client):
    fake_response = {
        "entities": {
            "Q12345": {
                "descriptions": {"en": {"language": "en", "value": "a famous mural"}}
            }
        }
    }
    client = WikidataClient(redis_client)
    with respx.mock:
        respx.get("https://www.wikidata.org/w/api.php").mock(
            return_value=httpx.Response(200, json=fake_response)
        )
        desc = await client.get_description("Q12345")
    assert desc == "a famous mural"


@pytest.mark.asyncio
async def test_get_description_returns_none_when_missing(redis_client):
    client = WikidataClient(redis_client)
    with respx.mock:
        respx.get("https://www.wikidata.org/w/api.php").mock(
            return_value=httpx.Response(200, json={"entities": {"Q12345": {}}})
        )
        desc = await client.get_description("Q12345")
    assert desc is None


@pytest.mark.asyncio
async def test_get_description_returns_none_on_error(redis_client):
    client = WikidataClient(redis_client)
    with respx.mock:
        respx.get("https://www.wikidata.org/w/api.php").mock(
            return_value=httpx.Response(500)
        )
        desc = await client.get_description("Q12345")
    assert desc is None  # fail open


@pytest.mark.asyncio
async def test_get_description_caches(redis_client):
    fake_response = {
        "entities": {
            "Q1": {"descriptions": {"en": {"value": "x"}}}
        }
    }
    client = WikidataClient(redis_client)
    with respx.mock:
        route = respx.get("https://www.wikidata.org/w/api.php").mock(
            return_value=httpx.Response(200, json=fake_response)
        )
        await client.get_description("Q1")
        await client.get_description("Q1")
    assert route.call_count == 1

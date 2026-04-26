import pytest


@pytest.mark.asyncio
async def test_healthz_returns_ok(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok"}

import pytest


@pytest.mark.asyncio
async def test_root_returns_operational(client):
    response = await client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "dispatch-zero"
    assert body["status"] == "operational"

import pytest


@pytest.mark.asyncio
async def test_config_endpoint_reflects_banner_setting(client, monkeypatch):
    monkeypatch.setenv("SHOW_BETA_BANNER", "true")
    r = await client.get("/config")
    assert r.status_code == 200
    assert r.json()["show_beta_banner"] is True


@pytest.mark.asyncio
async def test_config_endpoint_defaults_to_false(client, monkeypatch):
    monkeypatch.delenv("SHOW_BETA_BANNER", raising=False)
    r = await client.get("/config")
    assert r.status_code == 200
    assert r.json()["show_beta_banner"] is False


@pytest.mark.asyncio
async def test_config_endpoint_does_not_require_auth(client):
    """Banner is public; no session needed."""
    client.cookies.clear()
    r = await client.get("/config")
    assert r.status_code == 200

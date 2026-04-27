import pytest


@pytest.mark.asyncio
async def test_index_served_at_root(client):
    r = await client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "<!doctype html>" in body.lower() or "<!DOCTYPE html>" in body
    assert "Dispatch Zero" in body


@pytest.mark.asyncio
async def test_index_served_for_arbitrary_app_path(client):
    r = await client.get("/signup")
    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower() or "<!DOCTYPE html>" in r.text


@pytest.mark.asyncio
async def test_healthz_still_works(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_api_routes_not_swallowed_by_spa_fallback(client):
    r = await client.get("/auth/me")
    assert r.status_code == 401
    assert "html" not in r.headers.get("content-type", "").lower()


@pytest.mark.asyncio
async def test_manifest_served_with_correct_content_type(client):
    r = await client.get("/manifest.webmanifest")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "manifest" in ct or "json" in ct


@pytest.mark.asyncio
async def test_service_worker_served_at_root(client):
    r = await client.get("/service-worker.js")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "javascript" in ct


@pytest.mark.asyncio
async def test_avatar_served_from_static(client):
    r = await client.get("/static/avatars/zero-agency.png")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("image/")
    assert len(r.content) > 1000

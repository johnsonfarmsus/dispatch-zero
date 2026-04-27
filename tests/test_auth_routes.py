import pytest

SIGNUP_PAYLOAD = {
    "callsign": "Trevor_01",
    "password": "hunter2hunter2",
    "adventure_style": "agency",
}


@pytest.mark.asyncio
async def test_signup_creates_user_and_sets_session(client, db_session, redis_client):
    r = await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert r.status_code == 201
    body = r.json()
    assert body["callsign"] == "Trevor_01"
    assert body["adventure_style"] == "agency"
    assert "id" in body
    assert "password" not in body
    assert client.cookies.get("dz_session") is not None


@pytest.mark.asyncio
async def test_signup_rejects_duplicate_callsign_case_insensitive(
    client, db_session, redis_client
):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    r = await client.post(
        "/auth/signup",
        json={**SIGNUP_PAYLOAD, "callsign": "TREVOR_01"},
    )
    assert r.status_code == 409
    assert "already" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_succeeds_with_correct_password(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    client.cookies.clear()
    r = await client.post(
        "/auth/login",
        json={"callsign": "Trevor_01", "password": "hunter2hunter2"},
    )
    assert r.status_code == 200
    assert client.cookies.get("dz_session") is not None


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    client.cookies.clear()
    r = await client.post(
        "/auth/login",
        json={"callsign": "Trevor_01", "password": "wrong-password!!"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


@pytest.mark.asyncio
async def test_login_rejects_unknown_callsign(client, db_session, redis_client):
    r = await client.post(
        "/auth/login",
        json={"callsign": "ghost_99", "password": "hunter2hunter2"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


@pytest.mark.asyncio
async def test_login_is_rate_limited(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    client.cookies.clear()
    for _ in range(5):
        await client.post(
            "/auth/login",
            json={"callsign": "Trevor_01", "password": "wrong-password!!"},
        )
    r = await client.post(
        "/auth/login",
        json={"callsign": "Trevor_01", "password": "hunter2hunter2"},
    )
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_me_returns_401_without_cookie(client, db_session, redis_client):
    client.cookies.clear()
    r = await client.get("/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_user_with_cookie(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    r = await client.get("/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["callsign"] == "Trevor_01"
    assert body["adventure_style"] == "agency"


@pytest.mark.asyncio
async def test_change_style(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    r = await client.post("/auth/style", json={"adventure_style": "guild"})
    assert r.status_code == 200, r.text
    assert r.json()["adventure_style"] == "guild"


@pytest.mark.asyncio
async def test_change_style_requires_auth(client, db_session, redis_client):
    client.cookies.clear()
    r = await client.post("/auth/style", json={"adventure_style": "guild"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_change_style_rejects_unknown_style(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    r = await client.post("/auth/style", json={"adventure_style": "ranger"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_logout_clears_cookie(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    r = await client.post("/auth/logout")
    assert r.status_code == 204
    # cookie deleted (set with empty value + past expiry)
    r2 = await client.get("/auth/me")
    assert r2.status_code == 401

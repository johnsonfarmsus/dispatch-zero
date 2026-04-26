import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_db_fixture_can_query(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_redis_fixture_can_set_and_get(redis_client):
    await redis_client.set("smoke", "ok")
    assert await redis_client.get("smoke") == "ok"

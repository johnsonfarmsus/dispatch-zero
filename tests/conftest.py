import os

import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# In the test container, env vars are provided by docker-compose.test.yml.
# We don't set defaults here — if the env isn't set, the test should fail loudly.
assert os.environ.get("DATABASE_URL"), "DATABASE_URL must be set (run via docker-compose.test.yml)"
assert os.environ.get("REDIS_URL"), "REDIS_URL must be set (run via docker-compose.test.yml)"
assert os.environ.get("SESSION_SECRET"), "SESSION_SECRET must be set"

from dispatchzero.main import app  # noqa: E402
from dispatchzero.models import Base  # noqa: E402

_schema_initialized = False


async def _ensure_schema(engine) -> None:
    """Create schema once per pytest invocation; subsequent tests skip."""
    global _schema_initialized
    if _schema_initialized:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    _schema_initialized = True


@pytest_asyncio.fixture
async def db_session():
    """Function-scoped engine + session — own loop per test, no cross-loop drama."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    await _ensure_schema(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def redis_client():
    client = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

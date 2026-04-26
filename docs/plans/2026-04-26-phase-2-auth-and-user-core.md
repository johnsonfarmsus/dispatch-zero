# Phase 2: Auth & User Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real users can sign up with a callsign + password, log in, log out, and pick an adventure style. Sessions persist across requests via signed cookies. Login attempts are rate-limited per IP via Redis. No email is collected anywhere.

**Architecture:** Three thin layers. (1) **Crypto helpers** — `argon2_hash` / `argon2_verify` and `sign_session` / `verify_session` are pure functions, fully unit-tested in isolation. (2) **Data layer** — single `User` SQLAlchemy model with case-insensitive callsign lookup via a separate `callsign_lower` indexed column. (3) **HTTP layer** — four endpoints (`POST /auth/signup`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`) plus a `current_user` FastAPI dependency that protected routes will reuse from Phase 5 onward. Rate limiting is a Redis `INCR + EXPIRE` middleware on `/auth/login` only; absolute rule, no headers, no leaked timings. Sessions are 30-day idle cookies, refreshed (re-issued) on each authenticated request.

**Tech stack additions:** `argon2-cffi` (password hashing), `itsdangerous` (cookie signing), `respx` (no, not needed in Phase 2 — keep deps lean), and the existing `redis` library for the rate limiter. Tests get a real Postgres test database (`dispatchzero_test`) created/dropped once per test session — no transaction-rollback gymnastics.

**Decision defaults (override in writing if any are wrong before we start):**

| Decision | Default | Why |
|---|---|---|
| Callsign storage | Two columns: `callsign` (display, as-typed) + `callsign_lower` (unique index, lookup). | Lets users see "Trevor" not "trevor", while uniqueness is case-insensitive. |
| Callsign character set | `^[a-zA-Z0-9_-]{3,32}$` | Common-sense readable, no spaces, no Unicode confusables. |
| Password rules | min 8, max 128, allow any printable Unicode, no complexity rules. | NIST SP 800-63B current guidance. |
| Cookie name | `dz_session` | Short, namespaced, unambiguous. |
| Cookie attrs | `HttpOnly`, `Secure`, `SameSite=Lax`, no `Domain` (host-only). | Standard hardening; host-only avoids accidental subdomain leakage. |
| Cookie max age | 30 days idle, refreshed on every authenticated request. | Spec'd in our design memory. |
| Rate limit | 5 failed `/auth/login` attempts per IP per 15 min sliding via Redis `INCR/EXPIRE`. Successful login does NOT reset the counter (keeps brute force expensive). | Simple, effective, no false-confidence resets. |
| Login error messages | Always `{"detail": "invalid credentials"}` — never leak whether callsign exists. | Standard. |
| Adventure style | Pydantic enum: `pulp` \| `agency` \| `guild`. Required at signup, mutable later. | Matches spec. |
| Test DB | Separate Postgres database `dispatchzero_test` on the same instance, dropped + recreated per session. | Real DB > mocks for integration safety. |

**Repo layout deltas after this phase:**

```
dispatch-zero/
├── src/dispatchzero/
│   ├── (existing)
│   ├── auth/                          # NEW package
│   │   ├── __init__.py
│   │   ├── passwords.py               # argon2 hash/verify
│   │   ├── sessions.py                # cookie sign/verify
│   │   ├── ratelimit.py               # Redis INCR/EXPIRE
│   │   ├── deps.py                    # current_user FastAPI dep
│   │   └── routes.py                  # /auth/* endpoints
│   ├── models/                        # NEW package
│   │   ├── __init__.py
│   │   ├── base.py                    # SQLAlchemy DeclarativeBase
│   │   └── user.py                    # User model
│   └── schemas/                       # NEW package (Pydantic)
│       ├── __init__.py
│       └── auth.py                    # SignupIn, LoginIn, MeOut
├── alembic/versions/
│   └── 0002_users.py                  # NEW migration
└── tests/
    ├── (existing)
    ├── conftest.py                    # extended with db + redis fixtures
    ├── test_passwords.py              # NEW
    ├── test_sessions.py               # NEW
    ├── test_ratelimit.py              # NEW
    └── test_auth_routes.py            # NEW (integration)
```

---

### Task 1: Add deps and extend Settings

**Files:**
- Modify: `pyproject.toml` (add `argon2-cffi`, `itsdangerous`)
- Modify: `src/dispatchzero/config.py` (add session cookie settings)
- Create: `tests/test_config_session.py`

- [ ] **Step 1.1: Add deps**

In `pyproject.toml`, add to `dependencies`:

```toml
    "argon2-cffi>=23.1",
    "itsdangerous>=2.2",
```

Then sync:

```bash
uv sync
```

- [ ] **Step 1.2: Write failing test for new Settings fields**

Write to `tests/test_config_session.py`:

```python
from dispatchzero.config import Settings


def test_session_settings_have_sensible_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    s = Settings()
    assert s.session_cookie_name == "dz_session"
    assert s.session_cookie_max_age_seconds == 60 * 60 * 24 * 30  # 30 days
    assert s.login_rate_limit_max == 5
    assert s.login_rate_limit_window_seconds == 60 * 15
```

- [ ] **Step 1.3: Run, confirm fail**

```bash
uv run pytest tests/test_config_session.py -v
```

Expected: AttributeError on `session_cookie_name`.

- [ ] **Step 1.4: Add fields to Settings**

In `src/dispatchzero/config.py`, extend the `Settings` class:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    session_secret: str = Field(min_length=32)
    app_env: str = "development"
    log_level: str = "INFO"

    # Sessions
    session_cookie_name: str = "dz_session"
    session_cookie_max_age_seconds: int = 60 * 60 * 24 * 30  # 30 days

    # Auth rate limit (login only)
    login_rate_limit_max: int = 5
    login_rate_limit_window_seconds: int = 60 * 15  # 15 min
```

- [ ] **Step 1.5: Run, confirm pass**

```bash
uv run pytest tests/test_config_session.py tests/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 1.6: Commit**

```bash
git add pyproject.toml uv.lock src/dispatchzero/config.py tests/test_config_session.py
git commit -m "feat: add argon2/itsdangerous deps and session cookie settings"
```

---

### Task 2: SQLAlchemy Base + User model + migration

**Files:**
- Create: `src/dispatchzero/models/__init__.py`
- Create: `src/dispatchzero/models/base.py`
- Create: `src/dispatchzero/models/user.py`
- Modify: `alembic/env.py` (wire `target_metadata`)
- Create: `alembic/versions/0002_users.py`

- [ ] **Step 2.1: Create models package and Base**

Write to `src/dispatchzero/models/__init__.py`:

```python
from dispatchzero.models.base import Base
from dispatchzero.models.user import User

__all__ = ["Base", "User"]
```

Write to `src/dispatchzero/models/base.py`:

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 2.2: Create User model**

Write to `src/dispatchzero/models/user.py`:

```python
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class AdventureStyle(StrEnum):
    PULP = "pulp"
    AGENCY = "agency"
    GUILD = "guild"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    callsign: Mapped[str] = mapped_column(String(32), nullable=False)
    callsign_lower: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    adventure_style: Mapped[str] = mapped_column(String(16), nullable=False)

    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rank: Mapped[str] = mapped_column(String(32), default="recruit", nullable=False)
    missions_this_week: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missions_last_week: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_users_callsign_lower", "callsign_lower"),)
```

- [ ] **Step 2.3: Wire Alembic target_metadata**

In `alembic/env.py`, replace `target_metadata = None` with:

```python
from dispatchzero.models import Base

target_metadata = Base.metadata
```

- [ ] **Step 2.4: Generate the migration**

Make sure VPS 2 stack is running so Postgres is up locally? — no, we don't run docker locally. Generate the migration **against the running prod DB** by SSHing in:

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app alembic revision --autogenerate -m 'add users table'"
```

This will write a new file in the running container under `/app/alembic/versions/`. We need to copy it back. Actually, **don't autogenerate against prod**. Instead, write the migration by hand — it's small, deterministic, and removes the need for round-tripping container files.

Write to `alembic/versions/0002_users.py`:

```python
"""add users table

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("callsign", sa.String(32), nullable=False),
        sa.Column("callsign_lower", sa.String(32), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("adventure_style", sa.String(16), nullable=False),
        sa.Column("xp", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rank", sa.String(32), nullable=False, server_default="recruit"),
        sa.Column("missions_this_week", sa.Integer, nullable=False, server_default="0"),
        sa.Column("missions_last_week", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_callsign_lower", "users", ["callsign_lower"])


def downgrade() -> None:
    op.drop_index("ix_users_callsign_lower", table_name="users")
    op.drop_table("users")
```

- [ ] **Step 2.5: Commit**

```bash
git add src/dispatchzero/models alembic/env.py alembic/versions/0002_users.py
git commit -m "feat: add User model and 0002 migration"
```

---

### Task 3: Test DB fixtures (db + redis)

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/.env.test` (NOT committed; or use env vars in conftest)

- [ ] **Step 3.1: Decide test DB strategy and document it**

Tests need a real Postgres + Redis to exercise the full auth surface. Two clean options:

- **Option A (recommended):** Run Postgres + Redis on **VPS 2** (already there). Tests run from local laptop pointing at exposed-via-SSH-tunnel ports. Fast on a stable network.
- **Option B:** Skip integration tests in CI; only run them on a deploy preview against the real stack.

For Phase 2 we go with **Option A** but the SSH tunnel is opened manually before running tests:

```bash
# In a separate shell, open tunnels (leave running while iterating):
ssh -N -L 15432:localhost:5432 -L 16379:localhost:6379 root@89.167.39.152 \
  "docker compose -f /opt/dispatchzero/docker-compose.yml \
   -f /opt/dispatchzero/docker-compose.prod.yml exec -T db true" \
  &  # background
# Or simpler — exec into the VPS and forward:
ssh -N -L 15432:127.0.0.1:5432 -L 16379:127.0.0.1:6379 root@89.167.39.152
```

Wait — DB and Redis aren't exposed on the host network in prod (we set `ports: !reset []`). So SSH port-forwarding to `localhost:5432` on the VPS won't work — the container ports aren't bound to host loopback. We have three sub-options:

  - **3a. Add a host-loopback exposure on the VPS for testing only.** Edit `docker-compose.prod.yml` to expose `127.0.0.1:5432` and `127.0.0.1:6379`. Slight increase in attack surface, but only on loopback.
  - **3b. Use `docker compose exec` to tunnel directly into containers.** More fragile.
  - **3c. Run a separate test stack locally.** Trevor doesn't want local Docker.

Pick **3a**. It's the least friction, only loopback-bound.

- [ ] **Step 3.2: Modify `docker-compose.prod.yml` to expose DB and Redis on VPS loopback**

In `docker-compose.prod.yml`, replace the `db:` and `redis:` sections:

```yaml
  db:
    restart: unless-stopped
    ports:
      - "127.0.0.1:5432:5432"   # loopback-only on VPS, accessible via SSH tunnel for tests

  redis:
    restart: unless-stopped
    ports:
      - "127.0.0.1:6379:6379"   # loopback-only on VPS, accessible via SSH tunnel for tests
```

(Keep `restart: unless-stopped` on caddy and app as before.)

Deploy this change before running Phase 2 integration tests:

```bash
./deploy/deploy.sh
```

- [ ] **Step 3.3: Create a dedicated test database on VPS 2**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d postgres -c 'CREATE DATABASE dispatchzero_test;'"
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero_test -c 'CREATE EXTENSION IF NOT EXISTS postgis;'"
```

- [ ] **Step 3.4: Open a persistent SSH tunnel for test runs**

In a separate shell (leave open while iterating on tests):

```bash
ssh -N -L 15432:127.0.0.1:5432 -L 16379:127.0.0.1:6379 root@89.167.39.152
```

(Local ports 15432 / 16379 are intentionally non-default to avoid colliding with anything.)

- [ ] **Step 3.5: Extend conftest.py with DB and Redis fixtures**

Replace `tests/conftest.py` entirely with:

```python
import asyncio
import os
import uuid

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Set env BEFORE importing anything that reads settings
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://dispatchzero:CHANGE_ME@127.0.0.1:15432/dispatchzero_test",
)
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:16379/1")
os.environ.setdefault("SESSION_SECRET", "x" * 32)

from dispatchzero.main import app  # noqa: E402
from dispatchzero.models import Base  # noqa: E402


@pytest_asyncio.fixture(scope="session")
async def _engine():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(_engine):
    Session = async_sessionmaker(_engine, expire_on_commit=False)
    async with Session() as session:
        yield session
        await session.rollback()


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
```

(Replace `CHANGE_ME` in `DATABASE_URL` with the real Postgres password from VPS 2's `/opt/dispatchzero/.env`. To avoid checking the password into the repo, expect testers to set `DATABASE_URL` env var explicitly via a local `.env.test` they don't commit; the `setdefault` above is for guidance.)

Actually, a cleaner approach — use a local `.env.test` (gitignored) and have conftest load it:

Update conftest.py top:

```python
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env.test", override=False)
os.environ.setdefault("SESSION_SECRET", "x" * 32)
```

And add `python-dotenv` to dev deps in pyproject.toml. Then create a local `.env.test` (NOT committed — already gitignored via `.env*` pattern? Check: our gitignore has `.env` only. Add `.env*` to be safe.)

- [ ] **Step 3.6: Update gitignore for .env* files**

In `.gitignore`, replace:

```
.env
```

with:

```
.env
.env.*
```

- [ ] **Step 3.7: Add python-dotenv as dev dep**

In `pyproject.toml`:

```toml
[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "httpx>=0.28",
    "ruff>=0.8",
    "python-dotenv>=1.0",
]
```

```bash
uv sync
```

- [ ] **Step 3.8: Create local `.env.test` (NOT committed)**

```bash
cat > .env.test <<'EOF'
DATABASE_URL=postgresql+asyncpg://dispatchzero:PASTE_PG_PASSWORD@127.0.0.1:15432/dispatchzero_test
REDIS_URL=redis://127.0.0.1:16379/1
SESSION_SECRET=test-only-secret-padded-to-32-chars
EOF
```

Replace `PASTE_PG_PASSWORD` with the prod Postgres password from VPS 2's `/opt/dispatchzero/.env` (read it via `ssh root@89.167.39.152 'grep POSTGRES_PASSWORD /opt/dispatchzero/.env'`).

- [ ] **Step 3.9: Verify the test fixtures work with a smoke test**

Add to `tests/test_db_smoke.py`:

```python
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
```

```bash
uv run pytest tests/test_db_smoke.py -v
```

Expected: 2 passed (with SSH tunnel running). If "Connection refused", the tunnel isn't open.

- [ ] **Step 3.10: Commit**

```bash
git add .gitignore pyproject.toml uv.lock tests/conftest.py tests/test_db_smoke.py docker-compose.prod.yml
git commit -m "feat: test fixtures for db and redis via VPS SSH tunnel"
```

---

### Task 4: Password hashing helpers (TDD, pure unit)

**Files:**
- Create: `src/dispatchzero/auth/__init__.py`
- Create: `src/dispatchzero/auth/passwords.py`
- Create: `tests/test_passwords.py`

- [ ] **Step 4.1: Write failing tests**

Write to `tests/test_passwords.py`:

```python
import pytest

from dispatchzero.auth.passwords import hash_password, verify_password


def test_hash_password_returns_argon2_string():
    h = hash_password("hunter2hunter2")
    assert h.startswith("$argon2id$")
    assert len(h) > 50


def test_hash_password_is_non_deterministic():
    h1 = hash_password("hunter2hunter2")
    h2 = hash_password("hunter2hunter2")
    assert h1 != h2  # salted


def test_verify_password_accepts_correct():
    h = hash_password("hunter2hunter2")
    assert verify_password("hunter2hunter2", h) is True


def test_verify_password_rejects_wrong():
    h = hash_password("hunter2hunter2")
    assert verify_password("wrong-password!!", h) is False


def test_verify_password_rejects_garbage_hash():
    assert verify_password("hunter2hunter2", "not-a-real-hash") is False
```

- [ ] **Step 4.2: Run, confirm import error**

```bash
uv run pytest tests/test_passwords.py -v
```

Expected: ImportError on `dispatchzero.auth.passwords`.

- [ ] **Step 4.3: Implement**

Write to `src/dispatchzero/auth/__init__.py`:

```python
```
(empty)

Write to `src/dispatchzero/auth/passwords.py`:

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False
```

- [ ] **Step 4.4: Run, confirm pass**

```bash
uv run pytest tests/test_passwords.py -v
```

Expected: 5 passed.

- [ ] **Step 4.5: Commit**

```bash
git add src/dispatchzero/auth tests/test_passwords.py
git commit -m "feat: argon2id password hashing helpers"
```

---

### Task 5: Session sign/verify helpers (TDD, pure unit)

**Files:**
- Create: `src/dispatchzero/auth/sessions.py`
- Create: `tests/test_sessions.py`

- [ ] **Step 5.1: Write failing tests**

Write to `tests/test_sessions.py`:

```python
import time
import uuid

import pytest

from dispatchzero.auth.sessions import sign_session, verify_session


def test_sign_then_verify_roundtrip():
    user_id = uuid.uuid4()
    cookie = sign_session(user_id)
    assert isinstance(cookie, str) and len(cookie) > 20
    parsed = verify_session(cookie, max_age_seconds=60)
    assert parsed == user_id


def test_verify_rejects_tampered_cookie():
    user_id = uuid.uuid4()
    cookie = sign_session(user_id)
    tampered = cookie[:-2] + "xx"
    assert verify_session(tampered, max_age_seconds=60) is None


def test_verify_rejects_expired_cookie():
    user_id = uuid.uuid4()
    cookie = sign_session(user_id)
    time.sleep(1.1)
    assert verify_session(cookie, max_age_seconds=1) is None


def test_verify_rejects_garbage():
    assert verify_session("not-a-real-cookie", max_age_seconds=60) is None
```

- [ ] **Step 5.2: Run, confirm import error**

```bash
uv run pytest tests/test_sessions.py -v
```

Expected: ImportError.

- [ ] **Step 5.3: Implement**

Write to `src/dispatchzero/auth/sessions.py`:

```python
import uuid

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from dispatchzero.config import get_settings


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="dz_session_v1")


def sign_session(user_id: uuid.UUID) -> str:
    return _serializer().dumps(str(user_id))


def verify_session(cookie: str, max_age_seconds: int) -> uuid.UUID | None:
    try:
        raw = _serializer().loads(cookie, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 5.4: Run, confirm pass**

```bash
uv run pytest tests/test_sessions.py -v
```

Expected: 4 passed.

- [ ] **Step 5.5: Commit**

```bash
git add src/dispatchzero/auth/sessions.py tests/test_sessions.py
git commit -m "feat: signed session cookie helpers via itsdangerous"
```

---

### Task 6: Redis-backed login rate limiter (TDD)

**Files:**
- Create: `src/dispatchzero/auth/ratelimit.py`
- Create: `tests/test_ratelimit.py`

- [ ] **Step 6.1: Write failing tests**

Write to `tests/test_ratelimit.py`:

```python
import asyncio

import pytest

from dispatchzero.auth.ratelimit import LoginRateLimiter


@pytest.mark.asyncio
async def test_first_n_attempts_allowed(redis_client):
    limiter = LoginRateLimiter(redis_client, max_attempts=3, window_seconds=60)
    for _ in range(3):
        assert await limiter.is_allowed("1.2.3.4") is True
        await limiter.record_failure("1.2.3.4")
    assert await limiter.is_allowed("1.2.3.4") is False


@pytest.mark.asyncio
async def test_different_ips_independent(redis_client):
    limiter = LoginRateLimiter(redis_client, max_attempts=2, window_seconds=60)
    for _ in range(2):
        await limiter.record_failure("1.2.3.4")
    assert await limiter.is_allowed("1.2.3.4") is False
    assert await limiter.is_allowed("5.6.7.8") is True


@pytest.mark.asyncio
async def test_window_expires(redis_client):
    limiter = LoginRateLimiter(redis_client, max_attempts=1, window_seconds=1)
    await limiter.record_failure("1.2.3.4")
    assert await limiter.is_allowed("1.2.3.4") is False
    await asyncio.sleep(1.1)
    assert await limiter.is_allowed("1.2.3.4") is True
```

- [ ] **Step 6.2: Run, confirm fail**

```bash
uv run pytest tests/test_ratelimit.py -v
```

Expected: ImportError.

- [ ] **Step 6.3: Implement**

Write to `src/dispatchzero/auth/ratelimit.py`:

```python
import redis.asyncio as aioredis


class LoginRateLimiter:
    def __init__(
        self,
        redis: aioredis.Redis,
        max_attempts: int,
        window_seconds: int,
    ) -> None:
        self._r = redis
        self._max = max_attempts
        self._window = window_seconds

    @staticmethod
    def _key(ip: str) -> str:
        return f"rl:login:{ip}"

    async def is_allowed(self, ip: str) -> bool:
        count = await self._r.get(self._key(ip))
        return count is None or int(count) < self._max

    async def record_failure(self, ip: str) -> None:
        key = self._key(ip)
        # Atomic INCR; set TTL on first increment only (NX prevents extending the window).
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, self._window, nx=True)
            await pipe.execute()
```

- [ ] **Step 6.4: Run, confirm pass**

```bash
uv run pytest tests/test_ratelimit.py -v
```

Expected: 3 passed.

- [ ] **Step 6.5: Commit**

```bash
git add src/dispatchzero/auth/ratelimit.py tests/test_ratelimit.py
git commit -m "feat: redis login rate limiter (5/15min default)"
```

---

### Task 7: Auth schemas (Pydantic)

**Files:**
- Create: `src/dispatchzero/schemas/__init__.py`
- Create: `src/dispatchzero/schemas/auth.py`
- Create: `tests/test_schemas_auth.py`

- [ ] **Step 7.1: Write failing tests**

Write to `tests/test_schemas_auth.py`:

```python
import pytest
from pydantic import ValidationError

from dispatchzero.schemas.auth import LoginIn, MeOut, SignupIn


def test_signup_accepts_valid_payload():
    s = SignupIn(callsign="Trevor_01", password="hunter2hunter2", adventure_style="agency")
    assert s.callsign == "Trevor_01"


def test_signup_rejects_short_callsign():
    with pytest.raises(ValidationError):
        SignupIn(callsign="ab", password="hunter2hunter2", adventure_style="agency")


def test_signup_rejects_bad_callsign_chars():
    with pytest.raises(ValidationError):
        SignupIn(callsign="hi there", password="hunter2hunter2", adventure_style="agency")


def test_signup_rejects_short_password():
    with pytest.raises(ValidationError):
        SignupIn(callsign="agent01", password="short1", adventure_style="agency")


def test_signup_rejects_unknown_style():
    with pytest.raises(ValidationError):
        SignupIn(callsign="agent01", password="hunter2hunter2", adventure_style="ranger")


def test_login_minimal():
    login = LoginIn(callsign="Trevor_01", password="hunter2hunter2")
    assert login.callsign == "Trevor_01"
```

- [ ] **Step 7.2: Run, confirm fail**

```bash
uv run pytest tests/test_schemas_auth.py -v
```

Expected: ImportError.

- [ ] **Step 7.3: Implement**

Write to `src/dispatchzero/schemas/__init__.py`:

```python
```
(empty)

Write to `src/dispatchzero/schemas/auth.py`:

```python
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

CallsignStr = Annotated[
    str,
    StringConstraints(pattern=r"^[a-zA-Z0-9_-]{3,32}$"),
]
PasswordStr = Annotated[str, Field(min_length=8, max_length=128)]
AdventureStyle = Literal["pulp", "agency", "guild"]


class SignupIn(BaseModel):
    callsign: CallsignStr
    password: PasswordStr
    adventure_style: AdventureStyle


class LoginIn(BaseModel):
    callsign: CallsignStr
    password: PasswordStr


class MeOut(BaseModel):
    id: uuid.UUID
    callsign: str
    adventure_style: str
    xp: int
    rank: str
```

- [ ] **Step 7.4: Run, confirm pass**

```bash
uv run pytest tests/test_schemas_auth.py -v
```

Expected: 6 passed.

- [ ] **Step 7.5: Commit**

```bash
git add src/dispatchzero/schemas tests/test_schemas_auth.py
git commit -m "feat: pydantic schemas for signup/login/me"
```

---

### Task 8: Auth dependency (`current_user`)

**Files:**
- Create: `src/dispatchzero/auth/deps.py`

(No standalone tests — exercised through the endpoints in Task 9. We could add narrow unit tests with a manually-constructed `Request`, but that's extra ceremony for a dep that the integration tests cover comprehensively.)

- [ ] **Step 8.1: Implement**

Write to `src/dispatchzero/auth/deps.py`:

```python
import uuid
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.sessions import verify_session
from dispatchzero.config import get_settings
from dispatchzero.db import get_session
from dispatchzero.models import User


async def current_user(
    db: Annotated[AsyncSession, Depends(get_session)],
    dz_session: Annotated[str | None, Cookie()] = None,
) -> User:
    if dz_session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")

    settings = get_settings()
    user_id: uuid.UUID | None = verify_session(
        dz_session, max_age_seconds=settings.session_cookie_max_age_seconds
    )
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session invalid or expired")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
    return user
```

- [ ] **Step 8.2: Commit**

```bash
git add src/dispatchzero/auth/deps.py
git commit -m "feat: current_user FastAPI dependency"
```

---

### Task 9: Auth routes (signup, login, logout, me) with integration tests

**Files:**
- Create: `src/dispatchzero/auth/routes.py`
- Modify: `src/dispatchzero/main.py` (mount router)
- Create: `tests/test_auth_routes.py`

- [ ] **Step 9.1: Write the integration test file**

Write to `tests/test_auth_routes.py`:

```python
import pytest

SIGNUP_PAYLOAD = {
    "callsign": "Trevor_01",
    "password": "hunter2hunter2",
    "adventure_style": "agency",
}


@pytest.mark.asyncio
async def test_signup_creates_user_and_sets_session(client):
    r = await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert r.status_code == 201
    body = r.json()
    assert body["callsign"] == "Trevor_01"
    assert body["adventure_style"] == "agency"
    assert "id" in body
    assert "password" not in body
    assert client.cookies.get("dz_session") is not None


@pytest.mark.asyncio
async def test_signup_rejects_duplicate_callsign_case_insensitive(client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    r = await client.post(
        "/auth/signup",
        json={**SIGNUP_PAYLOAD, "callsign": "TREVOR_01"},
    )
    assert r.status_code == 409
    assert "already" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_succeeds_with_correct_password(client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    client.cookies.clear()
    r = await client.post(
        "/auth/login",
        json={"callsign": "Trevor_01", "password": "hunter2hunter2"},
    )
    assert r.status_code == 200
    assert client.cookies.get("dz_session") is not None


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    client.cookies.clear()
    r = await client.post(
        "/auth/login",
        json={"callsign": "Trevor_01", "password": "wrong-password!!"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


@pytest.mark.asyncio
async def test_login_rejects_unknown_callsign(client):
    r = await client.post(
        "/auth/login",
        json={"callsign": "ghost_99", "password": "hunter2hunter2"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


@pytest.mark.asyncio
async def test_login_is_rate_limited(client, redis_client):
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
async def test_me_returns_401_without_cookie(client):
    client.cookies.clear()
    r = await client.get("/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_user_with_cookie(client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    r = await client.get("/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["callsign"] == "Trevor_01"
    assert body["adventure_style"] == "agency"


@pytest.mark.asyncio
async def test_logout_clears_cookie(client):
    await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    r = await client.post("/auth/logout")
    assert r.status_code == 204
    # cookie deleted (set with empty value + past expiry)
    r2 = await client.get("/auth/me")
    assert r2.status_code == 401
```

- [ ] **Step 9.2: Run, confirm fail**

```bash
uv run pytest tests/test_auth_routes.py -v
```

Expected: collection error or 404 on first signup call (router not mounted).

- [ ] **Step 9.3: Implement the routes**

Write to `src/dispatchzero/auth/routes.py`:

```python
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.deps import current_user
from dispatchzero.auth.passwords import hash_password, verify_password
from dispatchzero.auth.ratelimit import LoginRateLimiter
from dispatchzero.auth.sessions import sign_session
from dispatchzero.config import Settings, get_settings
from dispatchzero.db import get_session
from dispatchzero.models import User
from dispatchzero.schemas.auth import LoginIn, MeOut, SignupIn

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, user_id, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=sign_session(user_id),
        max_age=settings.session_cookie_max_age_seconds,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _get_redis(settings: Annotated[Settings, Depends(get_settings)]) -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=MeOut)
async def signup(
    payload: SignupIn,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeOut:
    callsign_lower = payload.callsign.lower()
    existing = await db.execute(
        select(User).where(User.callsign_lower == callsign_lower)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "callsign already taken")

    user = User(
        callsign=payload.callsign,
        callsign_lower=callsign_lower,
        password_hash=hash_password(payload.password),
        adventure_style=payload.adventure_style,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    _set_session_cookie(response, user.id, settings)
    return MeOut(
        id=user.id,
        callsign=user.callsign,
        adventure_style=user.adventure_style,
        xp=user.xp,
        rank=user.rank,
    )


@router.post("/login", status_code=status.HTTP_200_OK, response_model=MeOut)
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(_get_redis)],
) -> MeOut:
    ip = _client_ip(request)
    limiter = LoginRateLimiter(
        redis,
        max_attempts=settings.login_rate_limit_max,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    if not await limiter.is_allowed(ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many failed attempts; try again later",
        )

    result = await db.execute(
        select(User).where(User.callsign_lower == payload.callsign.lower())
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        await limiter.record_failure(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    _set_session_cookie(response, user.id, settings)
    return MeOut(
        id=user.id,
        callsign=user.callsign,
        adventure_style=user.adventure_style,
        xp=user.xp,
        rank=user.rank,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
    )


@router.get("/me", response_model=MeOut)
async def me(user: Annotated[User, Depends(current_user)]) -> MeOut:
    return MeOut(
        id=user.id,
        callsign=user.callsign,
        adventure_style=user.adventure_style,
        xp=user.xp,
        rank=user.rank,
    )
```

- [ ] **Step 9.4: Mount the router**

In `src/dispatchzero/main.py`, add the import and `include_router`:

```python
from fastapi import FastAPI

from dispatchzero.auth.routes import router as auth_router

app = FastAPI(title="Dispatch Zero")
app.include_router(auth_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "dispatch-zero", "status": "operational"}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 9.5: Run integration tests**

```bash
uv run pytest tests/test_auth_routes.py -v
```

Expected: 9 passed. Tests rely on the SSH tunnel from Task 3.4 being open.

- [ ] **Step 9.6: Run the full suite**

```bash
uv run pytest -v
```

Expected: all tests pass (config, healthz, root, passwords, sessions, ratelimit, schemas, db_smoke, auth_routes).

- [ ] **Step 9.7: Commit**

```bash
git add src/dispatchzero/auth/routes.py src/dispatchzero/main.py tests/test_auth_routes.py
git commit -m "feat: /auth/{signup,login,logout,me} endpoints with full integration tests"
```

---

### Task 10: Deploy and curl-verify in production

- [ ] **Step 10.1: Deploy**

```bash
./deploy/deploy.sh
```

Expected: deploy succeeds, alembic upgrades to `0002`.

- [ ] **Step 10.2: Verify migration applied in prod**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app alembic current"
```

Expected: `0002 (head)`.

- [ ] **Step 10.3: Curl a real signup → /me → logout flow against prod**

```bash
COOKIES=$(mktemp)

# Signup with a throwaway test callsign
curl -sS -c "$COOKIES" -X POST https://dispatchzero.ataary.com/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"callsign":"smoketest_001","password":"smoketest-very-long-password","adventure_style":"agency"}'
echo

# Hit /me with the cookie
curl -sS -b "$COOKIES" https://dispatchzero.ataary.com/auth/me
echo

# Logout
curl -sS -b "$COOKIES" -c "$COOKIES" -X POST -o /dev/null -w "%{http_code}\n" https://dispatchzero.ataary.com/auth/logout

# /me should now 401
curl -sS -b "$COOKIES" -o /dev/null -w "%{http_code}\n" https://dispatchzero.ataary.com/auth/me

rm -f "$COOKIES"
```

Expected:
- Signup returns the user JSON (no password field).
- `/me` returns the same callsign + style.
- Logout returns `204`.
- Subsequent `/me` returns `401`.

- [ ] **Step 10.4: Clean up the smoke-test user from prod**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -c \"DELETE FROM users WHERE callsign_lower = 'smoketest_001';\""
```

Expected: `DELETE 1`.

- [ ] **Step 10.5: Confirm Paperclip and resources are still healthy**

```bash
ssh root@89.167.39.152 "systemctl is-active paperclip.service && free -h && df -h /"
```

Expected: `active`, RAM available > 1.5 GB, disk used < 85%.

---

## Phase 2 — Definition of Done

- All tests in `tests/` pass against the test DB on VPS 2 via SSH tunnel.
- Production smoke-test flow (signup → /me → logout → /me 401) works against `https://dispatchzero.ataary.com`.
- Migration `0002` applied in production; `users` table exists with the indexed `callsign_lower` column.
- Login is rate-limited to 5 per IP per 15 min; 6th attempt returns 429.
- Wrong-password and unknown-callsign both return identical `{"detail": "invalid credentials"}`.
- Cookie is `HttpOnly`, `Secure` (in prod), `SameSite=Lax`, max age 30 days.
- Paperclip restart count unchanged.
- New deps (`argon2-cffi`, `itsdangerous`, `python-dotenv`) committed in `uv.lock`.

---

## Critical Files To Be Created In Phase 2

| File | Purpose |
|---|---|
| `src/dispatchzero/auth/passwords.py` | argon2id hash + verify |
| `src/dispatchzero/auth/sessions.py` | itsdangerous sign + verify |
| `src/dispatchzero/auth/ratelimit.py` | Redis INCR/EXPIRE limiter |
| `src/dispatchzero/auth/deps.py` | `current_user` FastAPI dep |
| `src/dispatchzero/auth/routes.py` | /auth/* endpoints |
| `src/dispatchzero/models/base.py` | DeclarativeBase |
| `src/dispatchzero/models/user.py` | User SQLAlchemy model |
| `src/dispatchzero/schemas/auth.py` | Pydantic schemas |
| `alembic/versions/0002_users.py` | Migration |
| `tests/conftest.py` | Extended with db_session, redis_client fixtures |
| `tests/test_*.py` | Unit tests per layer + integration test for routes |

---

## Open Decisions (default in plan, override before starting)

| Decision | Default | Where to change |
|---|---|---|
| Test DB strategy: SSH tunnel to VPS 2 vs. local Docker vs. hosted | SSH tunnel to VPS 2 (matches "no local Docker" preference) | Task 3 |
| DB/Redis loopback exposure on VPS for test tunnel | Yes (`127.0.0.1:5432`, `127.0.0.1:6379`) | Task 3.2 |
| Cookie name | `dz_session` | `Settings.session_cookie_name` |
| Rate limit window/max | 5 per 15 min per IP | `Settings.login_rate_limit_*` |
| Username/callsign char set | `^[a-zA-Z0-9_-]{3,32}$` | `schemas/auth.py` |
| Password min length | 8 | `schemas/auth.py` |
| Cookie refresh on every request | Yes (set on every authenticated response) | Could add middleware in a follow-up; current plan only refreshes on signup/login |

---

## What Comes Next After Phase 2

Phase 3 — Place discovery pipeline. Builds on the User model (per-user completion history filter), PostGIS (geo radius queries), and Redis (Nominatim/Overpass cache). The Phase 3 plan will be written using this same skill at the end of Phase 2.

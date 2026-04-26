# Phase 3: Place Discovery Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /places/nearby?lat=X&lng=Y&radius_m=2000&limit=10` returns a ranked list of real, eligible places within radius — geocoded from OSM, optionally enriched from Wikidata, scored for quest-worthiness, and filtered against the authenticated user's 90-day completion history. All external HTTP calls are aggressively cached in Redis. The endpoint is the upstream of Phase 4's mission generator.

**Architecture:** Five layers, each independently testable.

1. **External clients** (`integrations/`) — pure async wrappers around Nominatim (geocoding), Overpass (place query), and Wikidata (description enrichment). Each has its own Redis cache with a documented TTL. Each respects the upstream service's etiquette (User-Agent, rate limits).
2. **Domain models** (`models/`) — `Place` (the shared catalog) and `UserPlaceHistory` (per-user completion log; replaces the spec's `completed_place_ids` array because we need timestamps for the 90-day rule).
3. **Scoring** (`services/scoring.py`) — pure deterministic function `score_place(place_dict, context) -> float`. Table-driven tests.
4. **Discovery service** (`services/discovery.py`) — orchestrates the pipeline: geocode → overpass → enrich top N → upsert to Place table → filter against user history → sort by score → return top K.
5. **HTTP layer** (`places/routes.py`) — `GET /places/nearby` mounted under the auth-required prefix; uses the `current_user` dependency from Phase 2.

**Tech additions:** `httpx` (async HTTP), `respx` (test mocking — dev only), nothing else. Wikidata's API is plain HTTP, no SDK needed. Overpass is plain HTTP. Nominatim is plain HTTP.

**External-service rules (do not violate):**

| Service | Rule | How we honor it |
|---|---|---|
| Nominatim (public) | 1 req/sec absolute max, real User-Agent | App-level async throttle (`asyncio.Lock` + min-interval) + Redis cache (30 days) so most lookups never hit the network |
| Overpass (public) | ~10k queries/day soft cap; honor `Retry-After` | Redis cache (7 days) keyed on rounded coordinates + radius + category set; one retry on 429 with jittered backoff |
| Wikidata | No hard rate limit but be polite | Redis cache (30 days); fail open (return None) on any error |

**Decision defaults (override before starting if any are wrong):**

| Decision | Default | Why |
|---|---|---|
| Discovery radius | 2 km default, 100 m – 10 km clamped | Matches "small adventure" intent; 10 km cap prevents abuse |
| Result limit | 10 default, 1 – 50 clamped | Enough to give the AI selector real choice without bloating responses |
| Categories returned | All five (mural, sculpture, memorial, historic, viewpoint) | Spec says all in scope for v1 |
| Scoring weights | name (+1.0), description (+1.0), wikidata-linked (+0.5), prior-positive ratings (+ratio×2.0), category priority bonus, no-rating-yet neutral (+0.0) | First pass — tune later from real-world ratings |
| Place re-entry | Excluded for 90 days after last completion | Locked decision in spec; implemented via `UserPlaceHistory.last_completed_at` filter |
| Enrichment | Wikidata description only (NOT full Wikipedia article) | One HTTP call per place, plenty of context for mission generation, gracefully optional |
| Failure mode | If geocoding fails: 502; if Overpass fails: 502; if Wikidata fails: continue without enrichment | Geocoding/Overpass are required, Wikidata is gravy |
| Cache key for Overpass | `overpass:{lat:.3f}:{lng:.3f}:{radius_m}:{categories_hash}` | 0.001° ≈ 110 m → cache hits cluster nicely without being too coarse |
| Place upsert key | `(osm_type, osm_id)` unique constraint | OSM IDs are only unique within a type (node/way/relation) |

**Repo layout deltas after this phase:**

```
dispatch-zero/
├── src/dispatchzero/
│   ├── (existing)
│   ├── integrations/                  # NEW — pure external HTTP wrappers
│   │   ├── __init__.py
│   │   ├── _throttle.py               # async min-interval throttle
│   │   ├── _cache.py                  # tiny Redis JSON cache helper
│   │   ├── nominatim.py
│   │   ├── overpass.py
│   │   └── wikidata.py
│   ├── models/
│   │   ├── (existing: base.py, user.py)
│   │   ├── place.py                   # NEW — Place model + enums
│   │   └── user_place_history.py      # NEW
│   ├── services/                      # NEW
│   │   ├── __init__.py
│   │   ├── scoring.py
│   │   └── discovery.py
│   ├── schemas/
│   │   ├── (existing: auth.py)
│   │   └── places.py                  # NEW — PlaceOut, NearbyQuery
│   ├── places/                        # NEW
│   │   ├── __init__.py
│   │   └── routes.py                  # NEW — GET /places/nearby
│   └── tools/                         # NEW
│       ├── __init__.py
│       └── discover_places.py         # CLI: python -m dispatchzero.tools.discover_places
├── alembic/versions/
│   └── 0003_places_and_history.py     # NEW
└── tests/
    ├── (existing)
    ├── test_integrations_nominatim.py # NEW
    ├── test_integrations_overpass.py  # NEW
    ├── test_integrations_wikidata.py  # NEW
    ├── test_integrations_throttle.py  # NEW
    ├── test_scoring.py                # NEW (table-driven)
    ├── test_discovery.py              # NEW (integration over mocked externals)
    └── test_places_routes.py          # NEW (HTTP integration)
```

---

### Task 1: Add deps and bootstrap `integrations/` package

**Files:**
- Modify: `pyproject.toml` (add `httpx` to main deps, `respx` to dev)
- Create: `src/dispatchzero/integrations/__init__.py`
- Create: `src/dispatchzero/integrations/_throttle.py`
- Create: `src/dispatchzero/integrations/_cache.py`
- Create: `tests/test_integrations_throttle.py`

- [ ] **Step 1.1: Add deps**

In `pyproject.toml`, append to main `dependencies`:

```toml
    "httpx>=0.28",
```

And to `[dependency-groups].dev`:

```toml
    "respx>=0.22",
```

(`httpx` is already pulled in transitively for tests, but we want it explicit since the app code now imports it.)

```bash
uv sync
```

- [ ] **Step 1.2: Create the throttle module (TDD-first)**

Write to `tests/test_integrations_throttle.py`:

```python
import asyncio
import time

import pytest

from dispatchzero.integrations._throttle import MinIntervalThrottle


@pytest.mark.asyncio
async def test_throttle_does_not_delay_first_call():
    t = MinIntervalThrottle(min_interval_seconds=1.0)
    start = time.monotonic()
    async with t:
        pass
    assert time.monotonic() - start < 0.05


@pytest.mark.asyncio
async def test_throttle_enforces_gap_between_calls():
    t = MinIntervalThrottle(min_interval_seconds=0.5)
    async with t:
        pass
    start = time.monotonic()
    async with t:
        pass
    elapsed = time.monotonic() - start
    assert 0.45 <= elapsed <= 0.7  # ~0.5s gap with some scheduler slop


@pytest.mark.asyncio
async def test_throttle_serializes_concurrent_calls():
    t = MinIntervalThrottle(min_interval_seconds=0.3)
    async def call():
        async with t:
            return time.monotonic()
    starts = await asyncio.gather(call(), call(), call())
    starts.sort()
    assert starts[1] - starts[0] >= 0.28
    assert starts[2] - starts[1] >= 0.28
```

- [ ] **Step 1.3: Confirm fail**

```bash
./deploy/test.sh 2>&1 | grep test_integrations_throttle | head -5
```

Expected: ImportError on `dispatchzero.integrations._throttle`.

- [ ] **Step 1.4: Implement**

Write to `src/dispatchzero/integrations/__init__.py`:

```python
```
(empty)

Write to `src/dispatchzero/integrations/_throttle.py`:

```python
import asyncio
import time


class MinIntervalThrottle:
    """Async context manager that enforces a minimum gap between successive entries.

    Process-local. Sufficient for a single app process with sub-1-req/sec ceilings
    (Nominatim's stated limit). For multi-process coordination, swap for a
    Redis-token-bucket later.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self._lock = asyncio.Lock()
        self._min_interval = min_interval_seconds
        self._last_call: float = 0.0

    async def __aenter__(self) -> "MinIntervalThrottle":
        await self._lock.acquire()
        gap = time.monotonic() - self._last_call
        if gap < self._min_interval:
            await asyncio.sleep(self._min_interval - gap)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._last_call = time.monotonic()
        self._lock.release()
```

- [ ] **Step 1.5: Confirm pass**

```bash
./deploy/test.sh 2>&1 | tail -10
```

Expected: 3 new tests pass; total still includes Phase 1+2 (33 + 3 = 36).

- [ ] **Step 1.6: Implement the cache helper (no separate tests — exercised by integration tests)**

Write to `src/dispatchzero/integrations/_cache.py`:

```python
import json
from typing import Any

import redis.asyncio as aioredis


class JsonCache:
    """Thin Redis JSON cache. Keys are namespaced by the caller."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self._r = redis

    async def get(self, key: str) -> Any | None:
        raw = await self._r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        await self._r.set(key, json.dumps(value), ex=ttl_seconds)
```

- [ ] **Step 1.7: Commit**

```bash
git add pyproject.toml uv.lock src/dispatchzero/integrations tests/test_integrations_throttle.py
git commit -m "feat: integrations bootstrap (throttle, cache helper) + httpx/respx deps"
```

---

### Task 2: Place + UserPlaceHistory models + migration 0003

**Files:**
- Create: `src/dispatchzero/models/place.py`
- Create: `src/dispatchzero/models/user_place_history.py`
- Modify: `src/dispatchzero/models/__init__.py`
- Create: `alembic/versions/0003_places_and_history.py`

- [ ] **Step 2.1: Create the Place model**

Write to `src/dispatchzero/models/place.py`:

```python
import uuid
from datetime import datetime
from enum import StrEnum

from geoalchemy2 import Geography
from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class PlaceCategory(StrEnum):
    MURAL = "mural"
    SCULPTURE = "sculpture"
    MEMORIAL = "memorial"
    HISTORIC = "historic"
    VIEWPOINT = "viewpoint"


class PlaceStatus(StrEnum):
    ACTIVE = "active"
    FLAGGED = "flagged"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class Place(Base):
    __tablename__ = "places"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    osm_type: Mapped[str] = mapped_column(String(8), nullable=False)  # node|way|relation
    osm_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    coordinates = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    wikidata_id: Mapped[str | None] = mapped_column(String(16), nullable=True)

    quality_score: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    location_thumbs_up: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    location_thumbs_down: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("osm_type", "osm_id", name="uq_places_osm"),
        Index("ix_places_status_category", "status", "category"),
        Index(
            "ix_places_coordinates",
            "coordinates",
            postgresql_using="gist",
        ),
    )
```

- [ ] **Step 2.2: Create UserPlaceHistory**

Write to `src/dispatchzero/models/user_place_history.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class UserPlaceHistory(Base):
    __tablename__ = "user_place_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("places.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "place_id", name="uq_user_place"),
    )
```

- [ ] **Step 2.3: Register models**

Replace `src/dispatchzero/models/__init__.py`:

```python
from dispatchzero.models.base import Base
from dispatchzero.models.place import Place, PlaceCategory, PlaceStatus
from dispatchzero.models.user import AdventureStyle, User
from dispatchzero.models.user_place_history import UserPlaceHistory

__all__ = [
    "AdventureStyle",
    "Base",
    "Place",
    "PlaceCategory",
    "PlaceStatus",
    "User",
    "UserPlaceHistory",
]
```

- [ ] **Step 2.4: Write migration 0003 by hand**

Write to `alembic/versions/0003_places_and_history.py`:

```python
"""add places and user_place_history tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-26
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "places",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("osm_type", sa.String(8), nullable=False),
        sa.Column("osm_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column(
            "coordinates",
            sa.dialects.postgresql.ARRAY(sa.Float).with_variant(
                # we actually want geography(point,4326) — see below
                sa.String, "sqlite"
            )
            if False
            else sa.Column,
        ),
    )
    # The cleanest path for PostGIS columns in Alembic is raw SQL.
    op.execute("ALTER TABLE places DROP COLUMN coordinates")
    op.execute("ALTER TABLE places ADD COLUMN coordinates geography(Point, 4326) NOT NULL")
    op.add_column("places", sa.Column("tags", JSONB, nullable=False, server_default="{}"))
    op.add_column("places", sa.Column("description", sa.String, nullable=True))
    op.add_column("places", sa.Column("wikidata_id", sa.String(16), nullable=True))
    op.add_column(
        "places", sa.Column("quality_score", sa.Float, nullable=False, server_default="0")
    )
    op.add_column(
        "places",
        sa.Column("location_thumbs_up", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "places",
        sa.Column("location_thumbs_down", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "places", sa.Column("status", sa.String(16), nullable=False, server_default="active")
    )
    op.add_column(
        "places",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "places",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint("uq_places_osm", "places", ["osm_type", "osm_id"])
    op.create_index("ix_places_status_category", "places", ["status", "category"])
    op.execute(
        "CREATE INDEX ix_places_coordinates ON places USING gist (coordinates)"
    )

    op.create_table(
        "user_place_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "place_id",
            UUID(as_uuid=True),
            sa.ForeignKey("places.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "last_completed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_user_place", "user_place_history", ["user_id", "place_id"]
    )


def downgrade() -> None:
    op.drop_table("user_place_history")
    op.execute("DROP INDEX IF EXISTS ix_places_coordinates")
    op.drop_index("ix_places_status_category", table_name="places")
    op.drop_constraint("uq_places_osm", "places", type_="unique")
    op.drop_table("places")
```

**Note:** The Alembic ORM lacks first-class Geography support, so we create the table with a placeholder column then `ALTER` to the real geography type via raw SQL. This is the standard PostGIS-with-Alembic workaround.

Actually, simpler — use straight raw SQL for the whole table. Replace the migration body above with:

```python
def upgrade() -> None:
    op.execute("""
        CREATE TABLE places (
            id UUID PRIMARY KEY,
            osm_type VARCHAR(8) NOT NULL,
            osm_id BIGINT NOT NULL,
            name VARCHAR(200),
            category VARCHAR(16) NOT NULL,
            coordinates geography(Point, 4326) NOT NULL,
            tags JSONB NOT NULL DEFAULT '{}',
            description TEXT,
            wikidata_id VARCHAR(16),
            quality_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            location_thumbs_up INTEGER NOT NULL DEFAULT 0,
            location_thumbs_down INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_places_osm UNIQUE (osm_type, osm_id)
        );
        CREATE INDEX ix_places_status_category ON places (status, category);
        CREATE INDEX ix_places_coordinates ON places USING gist (coordinates);

        CREATE TABLE user_place_history (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
            last_completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_user_place UNIQUE (user_id, place_id)
        );
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS user_place_history;
        DROP TABLE IF EXISTS places;
    """)
```

Use this version. It's clearer than the SQLAlchemy DSL when geography is involved.

Also update `osm_id` in the Place model from `Integer` → `BigInteger` to match (`osm_id` can exceed 2^31 for relations). Update `src/dispatchzero/models/place.py` line:

```python
from sqlalchemy import BigInteger, ...
osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
```

- [ ] **Step 2.5: Run tests to confirm `Base.metadata` includes the new tables and the conftest schema-reset still works**

```bash
./deploy/test.sh 2>&1 | tail -5
```

Expected: all existing tests still pass (the per-test `Base.metadata.drop_all` + `create_all` will now create the new tables too; confirms model definitions are valid).

- [ ] **Step 2.6: Commit**

```bash
git add src/dispatchzero/models alembic/versions/0003_places_and_history.py
git commit -m "feat: add Place and UserPlaceHistory models with migration 0003"
```

---

### Task 3: Nominatim geocoding wrapper (TDD with respx)

**Files:**
- Create: `src/dispatchzero/integrations/nominatim.py`
- Create: `tests/test_integrations_nominatim.py`

- [ ] **Step 3.1: Write failing tests**

Write to `tests/test_integrations_nominatim.py`:

```python
import httpx
import pytest
import respx

from dispatchzero.integrations.nominatim import NominatimClient


@pytest.mark.asyncio
async def test_geocode_returns_lat_lng_on_hit(redis_client):
    client = NominatimClient(redis_client)
    with respx.mock:
        respx.get("https://nominatim.openstreetmap.org/search").mock(
            return_value=httpx.Response(
                200,
                json=[{"lat": "37.7749", "lon": "-122.4194", "display_name": "San Francisco"}],
            )
        )
        result = await client.geocode("San Francisco")
    assert result == {"lat": 37.7749, "lng": -122.4194, "display_name": "San Francisco"}


@pytest.mark.asyncio
async def test_geocode_returns_none_on_no_results(redis_client):
    client = NominatimClient(redis_client)
    with respx.mock:
        respx.get("https://nominatim.openstreetmap.org/search").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await client.geocode("nonsense_query_zzzz")
    assert result is None


@pytest.mark.asyncio
async def test_geocode_caches_response(redis_client):
    client = NominatimClient(redis_client)
    with respx.mock:
        route = respx.get("https://nominatim.openstreetmap.org/search").mock(
            return_value=httpx.Response(
                200,
                json=[{"lat": "1.0", "lon": "2.0", "display_name": "X"}],
            )
        )
        await client.geocode("X")
        await client.geocode("X")
    assert route.call_count == 1  # second call hit cache


@pytest.mark.asyncio
async def test_geocode_user_agent_is_set(redis_client):
    client = NominatimClient(redis_client)
    with respx.mock:
        route = respx.get("https://nominatim.openstreetmap.org/search").mock(
            return_value=httpx.Response(200, json=[])
        )
        await client.geocode("anywhere")
    request = route.calls.last.request
    assert "dispatchzero" in request.headers["User-Agent"].lower()
```

- [ ] **Step 3.2: Implement**

Write to `src/dispatchzero/integrations/nominatim.py`:

```python
from typing import Any

import httpx
import redis.asyncio as aioredis

from dispatchzero.integrations._cache import JsonCache
from dispatchzero.integrations._throttle import MinIntervalThrottle

_BASE_URL = "https://nominatim.openstreetmap.org"
_USER_AGENT = "dispatchzero/0.1 (trevor@johnsonfarms.us)"
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

# Module-level — one throttle per process. Nominatim's policy is 1 req/sec absolute.
_throttle = MinIntervalThrottle(min_interval_seconds=1.0)


class NominatimClient:
    def __init__(self, redis: aioredis.Redis, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._cache = JsonCache(redis)
        self._http = http_client or httpx.AsyncClient(
            timeout=10.0, headers={"User-Agent": _USER_AGENT}
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def geocode(self, query: str) -> dict[str, Any] | None:
        key = f"nominatim:geocode:{query.strip().lower()}"
        cached = await self._cache.get(key)
        if cached is not None:
            return cached if cached else None  # treat empty dict as "no result"

        async with _throttle:
            r = await self._http.get(
                f"{_BASE_URL}/search",
                params={"q": query, "format": "json", "limit": 1},
            )
        r.raise_for_status()
        data = r.json()
        if not data:
            await self._cache.set(key, {}, _CACHE_TTL_SECONDS)
            return None
        first = data[0]
        result = {
            "lat": float(first["lat"]),
            "lng": float(first["lon"]),
            "display_name": first.get("display_name", ""),
        }
        await self._cache.set(key, result, _CACHE_TTL_SECONDS)
        return result
```

- [ ] **Step 3.3: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | grep -E "test_integrations_nominatim|PASSED|FAILED" | tail -10
```

Expected: 4 passed.

- [ ] **Step 3.4: Commit**

```bash
git add src/dispatchzero/integrations/nominatim.py tests/test_integrations_nominatim.py
git commit -m "feat: nominatim geocoding wrapper with throttle and 30-day cache"
```

---

### Task 4: Overpass query wrapper (TDD)

**Files:**
- Create: `src/dispatchzero/integrations/overpass.py`
- Create: `tests/test_integrations_overpass.py`

- [ ] **Step 4.1: Write failing tests**

Write to `tests/test_integrations_overpass.py`:

```python
import httpx
import pytest
import respx

from dispatchzero.integrations.overpass import (
    OverpassClient,
    OverpassPlace,
    build_query,
)
from dispatchzero.models import PlaceCategory


def test_build_query_includes_all_categories():
    q = build_query(lat=37.7749, lng=-122.4194, radius_m=1000, categories=list(PlaceCategory))
    assert "[out:json]" in q
    assert "around:1000" in q
    assert "37.7749" in q
    assert "-122.4194" in q
    # Each category translates to specific tag filters
    assert "artwork_type" in q or "tourism=artwork" in q  # mural/sculpture
    assert "historic=memorial" in q
    assert "tourism=viewpoint" in q


@pytest.mark.asyncio
async def test_query_returns_normalized_places(redis_client):
    fake_response = {
        "elements": [
            {
                "type": "node",
                "id": 12345,
                "lat": 37.78,
                "lon": -122.41,
                "tags": {"name": "Some Mural", "tourism": "artwork", "artwork_type": "mural"},
            },
            {
                "type": "way",
                "id": 67890,
                "center": {"lat": 37.79, "lon": -122.42},
                "tags": {"name": "Old Building", "historic": "yes"},
            },
        ]
    }
    client = OverpassClient(redis_client)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json=fake_response)
        )
        results = await client.query_nearby(
            lat=37.7749, lng=-122.4194, radius_m=1000, categories=list(PlaceCategory)
        )
    assert len(results) == 2
    assert results[0].osm_type == "node"
    assert results[0].osm_id == 12345
    assert results[0].name == "Some Mural"
    assert results[1].osm_type == "way"
    assert results[1].lat == 37.79  # used 'center' for ways


@pytest.mark.asyncio
async def test_query_caches_response(redis_client):
    client = OverpassClient(redis_client)
    with respx.mock:
        route = respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json={"elements": []})
        )
        await client.query_nearby(lat=1.0, lng=2.0, radius_m=500, categories=[PlaceCategory.MURAL])
        await client.query_nearby(lat=1.0, lng=2.0, radius_m=500, categories=[PlaceCategory.MURAL])
    assert route.call_count == 1
```

- [ ] **Step 4.2: Implement**

Write to `src/dispatchzero/integrations/overpass.py`:

```python
import hashlib
from dataclasses import dataclass
from typing import Iterable

import httpx
import redis.asyncio as aioredis

from dispatchzero.integrations._cache import JsonCache
from dispatchzero.models import PlaceCategory

_BASE_URL = "https://overpass-api.de/api/interpreter"
_USER_AGENT = "dispatchzero/0.1 (trevor@johnsonfarms.us)"
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

# OSM tag selectors per category. Keep these explicit and reviewable.
_CATEGORY_FILTERS: dict[PlaceCategory, list[str]] = {
    PlaceCategory.MURAL: [
        '["artwork_type"="mural"]',
        '["tourism"="artwork"]["artwork_type"="mural"]',
    ],
    PlaceCategory.SCULPTURE: [
        '["tourism"="artwork"]["artwork_type"="sculpture"]',
        '["tourism"="artwork"]["artwork_type"="statue"]',
    ],
    PlaceCategory.MEMORIAL: ['["historic"="memorial"]', '["historic"="monument"]'],
    PlaceCategory.HISTORIC: ['["historic"="building"]', '["historic"="ruins"]', '["historic"="archaeological_site"]'],
    PlaceCategory.VIEWPOINT: ['["tourism"="viewpoint"]'],
}


@dataclass(frozen=True)
class OverpassPlace:
    osm_type: str
    osm_id: int
    lat: float
    lng: float
    tags: dict
    name: str | None
    category: PlaceCategory


def build_query(
    *,
    lat: float,
    lng: float,
    radius_m: int,
    categories: Iterable[PlaceCategory],
) -> str:
    parts: list[str] = []
    for cat in categories:
        for filt in _CATEGORY_FILTERS[cat]:
            parts.append(f"node{filt}(around:{radius_m},{lat},{lng});")
            parts.append(f"way{filt}(around:{radius_m},{lat},{lng});")
            parts.append(f"relation{filt}(around:{radius_m},{lat},{lng});")
    body = "(" + "".join(parts) + ");"
    return f"[out:json][timeout:25];{body}out center tags;"


def _cache_key(lat: float, lng: float, radius_m: int, categories: list[PlaceCategory]) -> str:
    cat_hash = hashlib.sha1(",".join(sorted(c.value for c in categories)).encode()).hexdigest()[:8]
    return f"overpass:{lat:.3f}:{lng:.3f}:{radius_m}:{cat_hash}"


def _classify(tags: dict) -> PlaceCategory | None:
    """Map an OSM element's tags to one of our categories. First match wins."""
    artwork_type = tags.get("artwork_type")
    if artwork_type == "mural":
        return PlaceCategory.MURAL
    if artwork_type in ("sculpture", "statue"):
        return PlaceCategory.SCULPTURE
    historic = tags.get("historic")
    if historic in ("memorial", "monument"):
        return PlaceCategory.MEMORIAL
    if historic in ("building", "ruins", "archaeological_site"):
        return PlaceCategory.HISTORIC
    if tags.get("tourism") == "viewpoint":
        return PlaceCategory.VIEWPOINT
    if tags.get("tourism") == "artwork":
        # Generic artwork without a specific type — treat as sculpture by default
        return PlaceCategory.SCULPTURE
    return None


class OverpassClient:
    def __init__(self, redis: aioredis.Redis, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._cache = JsonCache(redis)
        self._http = http_client or httpx.AsyncClient(
            timeout=30.0, headers={"User-Agent": _USER_AGENT}
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def query_nearby(
        self,
        *,
        lat: float,
        lng: float,
        radius_m: int,
        categories: list[PlaceCategory],
    ) -> list[OverpassPlace]:
        key = _cache_key(lat, lng, radius_m, categories)
        cached = await self._cache.get(key)
        if cached is not None:
            return [OverpassPlace(**dict(item, category=PlaceCategory(item["category"]))) for item in cached]

        query = build_query(lat=lat, lng=lng, radius_m=radius_m, categories=categories)
        r = await self._http.post(_BASE_URL, data={"data": query})
        r.raise_for_status()
        data = r.json()

        results: list[OverpassPlace] = []
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            cat = _classify(tags)
            if cat is None:
                continue
            if el["type"] == "node":
                lat_, lng_ = el.get("lat"), el.get("lon")
            else:
                center = el.get("center", {})
                lat_, lng_ = center.get("lat"), center.get("lon")
            if lat_ is None or lng_ is None:
                continue
            results.append(
                OverpassPlace(
                    osm_type=el["type"],
                    osm_id=el["id"],
                    lat=lat_,
                    lng=lng_,
                    tags=tags,
                    name=tags.get("name"),
                    category=cat,
                )
            )

        # Cache the serialized form (Place objects aren't directly JSON-serializable)
        await self._cache.set(
            key,
            [
                {
                    "osm_type": p.osm_type,
                    "osm_id": p.osm_id,
                    "lat": p.lat,
                    "lng": p.lng,
                    "tags": p.tags,
                    "name": p.name,
                    "category": p.category.value,
                }
                for p in results
            ],
            _CACHE_TTL_SECONDS,
        )
        return results
```

- [ ] **Step 4.3: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | grep -E "test_integrations_overpass|PASSED|FAILED" | tail -10
```

Expected: 3 new tests pass.

- [ ] **Step 4.4: Commit**

```bash
git add src/dispatchzero/integrations/overpass.py tests/test_integrations_overpass.py
git commit -m "feat: overpass query wrapper with 7-day cache and category filters"
```

---

### Task 5: Wikidata enrichment (TDD)

**Files:**
- Create: `src/dispatchzero/integrations/wikidata.py`
- Create: `tests/test_integrations_wikidata.py`

- [ ] **Step 5.1: Write failing tests**

Write to `tests/test_integrations_wikidata.py`:

```python
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
```

- [ ] **Step 5.2: Implement**

Write to `src/dispatchzero/integrations/wikidata.py`:

```python
import httpx
import redis.asyncio as aioredis

from dispatchzero.integrations._cache import JsonCache

_BASE_URL = "https://www.wikidata.org/w/api.php"
_USER_AGENT = "dispatchzero/0.1 (trevor@johnsonfarms.us)"
_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


class WikidataClient:
    def __init__(self, redis: aioredis.Redis, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._cache = JsonCache(redis)
        self._http = http_client or httpx.AsyncClient(
            timeout=10.0, headers={"User-Agent": _USER_AGENT}
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def get_description(self, qid: str) -> str | None:
        """Return the English Wikidata description for a Q-ID, or None on miss/error."""
        key = f"wikidata:desc:{qid}"
        cached = await self._cache.get(key)
        if cached is not None:
            return cached or None  # empty string sentinel = "we know there isn't one"

        try:
            r = await self._http.get(
                _BASE_URL,
                params={
                    "action": "wbgetentities",
                    "ids": qid,
                    "props": "descriptions",
                    "languages": "en",
                    "format": "json",
                },
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            return None  # fail open — Wikidata is enrichment, not required

        try:
            desc = data["entities"][qid]["descriptions"]["en"]["value"]
        except (KeyError, TypeError):
            await self._cache.set(key, "", _CACHE_TTL_SECONDS)
            return None

        await self._cache.set(key, desc, _CACHE_TTL_SECONDS)
        return desc
```

- [ ] **Step 5.3: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | grep -E "test_integrations_wikidata|PASSED|FAILED" | tail -10
```

Expected: 4 passed.

- [ ] **Step 5.4: Commit**

```bash
git add src/dispatchzero/integrations/wikidata.py tests/test_integrations_wikidata.py
git commit -m "feat: wikidata description enrichment with 30-day cache (fail-open)"
```

---

### Task 6: Quest-worthiness scoring (pure function, table-driven TDD)

**Files:**
- Create: `src/dispatchzero/services/__init__.py`
- Create: `src/dispatchzero/services/scoring.py`
- Create: `tests/test_scoring.py`

- [ ] **Step 6.1: Write failing tests**

Write to `tests/test_scoring.py`:

```python
import pytest

from dispatchzero.models import PlaceCategory
from dispatchzero.services.scoring import ScoreInput, score_place


@pytest.mark.parametrize(
    "input_,expected_min,expected_max",
    [
        # Bare-bones place — no name, no description, no rating history
        (ScoreInput(name=None, description=None, has_wikidata=False,
                    category=PlaceCategory.VIEWPOINT, thumbs_up=0, thumbs_down=0), 0.0, 0.5),
        # Named, described, wikidata-linked, no ratings yet — should be high
        (ScoreInput(name="Example", description="A famous landmark.", has_wikidata=True,
                    category=PlaceCategory.MURAL, thumbs_up=0, thumbs_down=0), 2.0, 4.0),
        # Highly upvoted mural — top tier
        (ScoreInput(name="Beloved", description="Big mural.", has_wikidata=True,
                    category=PlaceCategory.MURAL, thumbs_up=20, thumbs_down=0), 4.0, 10.0),
        # Mostly-downvoted place — penalty
        (ScoreInput(name="Bad", description="Hard to find.", has_wikidata=False,
                    category=PlaceCategory.HISTORIC, thumbs_up=1, thumbs_down=10), 0.0, 1.5),
    ],
)
def test_score_within_expected_range(input_, expected_min, expected_max):
    s = score_place(input_)
    assert expected_min <= s <= expected_max, f"got {s}"


def test_category_priority_mural_beats_viewpoint_all_else_equal():
    base = dict(name="X", description="Y", has_wikidata=False, thumbs_up=0, thumbs_down=0)
    mural = score_place(ScoreInput(**base, category=PlaceCategory.MURAL))
    viewpoint = score_place(ScoreInput(**base, category=PlaceCategory.VIEWPOINT))
    assert mural > viewpoint


def test_named_beats_unnamed():
    base = dict(description=None, has_wikidata=False,
                category=PlaceCategory.SCULPTURE, thumbs_up=0, thumbs_down=0)
    named = score_place(ScoreInput(name="Has a Name", **base))
    unnamed = score_place(ScoreInput(name=None, **base))
    assert named > unnamed
```

- [ ] **Step 6.2: Implement**

Write to `src/dispatchzero/services/__init__.py`:

```python
```
(empty)

Write to `src/dispatchzero/services/scoring.py`:

```python
from dataclasses import dataclass

from dispatchzero.models import PlaceCategory

# Category priority bonus — matches the priority ordering in the spec.
_CATEGORY_BONUS: dict[PlaceCategory, float] = {
    PlaceCategory.MURAL: 1.5,
    PlaceCategory.SCULPTURE: 1.2,
    PlaceCategory.MEMORIAL: 1.0,
    PlaceCategory.HISTORIC: 0.8,
    PlaceCategory.VIEWPOINT: 0.4,
}


@dataclass(frozen=True)
class ScoreInput:
    name: str | None
    description: str | None
    has_wikidata: bool
    category: PlaceCategory
    thumbs_up: int
    thumbs_down: int


def score_place(p: ScoreInput) -> float:
    """Deterministic quest-worthiness score. Higher = better candidate."""
    score = 0.0

    # Existence of metadata
    if p.name:
        score += 1.0
    if p.description:
        score += 1.0
    if p.has_wikidata:
        score += 0.5

    # Category priority
    score += _CATEGORY_BONUS.get(p.category, 0.0)

    # Rating signal — only matters once there's a sample
    total = p.thumbs_up + p.thumbs_down
    if total >= 1:
        ratio = p.thumbs_up / total
        # Centered around 0.5 → no effect when neutral, ±2.0 at extremes
        rating_effect = (ratio - 0.5) * 4.0
        # Confidence weight — single ratings count less than 10
        confidence = min(total, 10) / 10
        score += rating_effect * confidence

    return max(0.0, score)
```

- [ ] **Step 6.3: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | grep -E "test_scoring|PASSED|FAILED" | tail -10
```

Expected: 6 passed.

- [ ] **Step 6.4: Commit**

```bash
git add src/dispatchzero/services/__init__.py src/dispatchzero/services/scoring.py tests/test_scoring.py
git commit -m "feat: quest-worthiness scoring (pure, table-driven tests)"
```

---

### Task 7: Discovery service (orchestrator) (TDD)

**Files:**
- Create: `src/dispatchzero/services/discovery.py`
- Create: `tests/test_discovery.py`

- [ ] **Step 7.1: Write failing tests**

Write to `tests/test_discovery.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from sqlalchemy import select

from dispatchzero.models import Place, User, UserPlaceHistory
from dispatchzero.services.discovery import discover_nearby


def _overpass_response_with(*pairs: tuple[int, str, str]) -> dict:
    """Build a fake Overpass response: (osm_id, name, artwork_type) tuples."""
    return {
        "elements": [
            {
                "type": "node",
                "id": osm_id,
                "lat": 37.7749 + 0.001 * i,
                "lon": -122.4194 + 0.001 * i,
                "tags": {"name": name, "tourism": "artwork", "artwork_type": atype},
            }
            for i, (osm_id, name, atype) in enumerate(pairs)
        ]
    }


@pytest.mark.asyncio
async def test_discover_returns_results_and_persists_places(db_session, redis_client):
    user = User(
        callsign="Tester",
        callsign_lower="tester",
        password_hash="x",
        adventure_style="agency",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200,
                json=_overpass_response_with(
                    (1, "Mural One", "mural"),
                    (2, "Mural Two", "mural"),
                ),
            )
        )
        # Wikidata: no qid in tags → never called
        results = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )

    assert len(results) == 2
    # Both places persisted
    rows = (await db_session.execute(select(Place))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_discover_filters_recently_completed_places(db_session, redis_client):
    user = User(
        callsign="Tester",
        callsign_lower="tester",
        password_hash="x",
        adventure_style="agency",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200, json=_overpass_response_with((1, "Already Done", "mural"))
            )
        )
        # First call: place gets discovered + persisted
        first = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )
        assert len(first) == 1

        # Mark as completed
        history = UserPlaceHistory(
            user_id=user.id,
            place_id=first[0]["id"],
            last_completed_at=datetime.now(timezone.utc),
        )
        db_session.add(history)
        await db_session.commit()

        # Second call: filtered out
        second = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )
        assert len(second) == 0


@pytest.mark.asyncio
async def test_discover_includes_old_completion_after_90_days(db_session, redis_client):
    user = User(
        callsign="Tester",
        callsign_lower="tester",
        password_hash="x",
        adventure_style="agency",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200, json=_overpass_response_with((1, "Long Ago", "mural"))
            )
        )
        first = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )
        history = UserPlaceHistory(
            user_id=user.id,
            place_id=first[0]["id"],
            last_completed_at=datetime.now(timezone.utc) - timedelta(days=91),
        )
        db_session.add(history)
        await db_session.commit()

        second = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )
        assert len(second) == 1


@pytest.mark.asyncio
async def test_discover_filters_unnamed_places(db_session, redis_client):
    user = User(
        callsign="Tester",
        callsign_lower="tester",
        password_hash="x",
        adventure_style="agency",
    )
    db_session.add(user)
    await db_session.commit()

    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(
                200,
                json={
                    "elements": [
                        {
                            "type": "node", "id": 1, "lat": 37.78, "lon": -122.41,
                            "tags": {"tourism": "artwork", "artwork_type": "mural"},  # no name
                        },
                        {
                            "type": "node", "id": 2, "lat": 37.79, "lon": -122.42,
                            "tags": {"name": "Has a Name", "tourism": "artwork", "artwork_type": "mural"},
                        },
                    ]
                },
            )
        )
        results = await discover_nearby(
            db=db_session, redis=redis_client, user=user,
            lat=37.7749, lng=-122.4194, radius_m=1000, limit=10,
        )
    assert len(results) == 1
    assert results[0]["name"] == "Has a Name"
```

- [ ] **Step 7.2: Implement**

Write to `src/dispatchzero/services/discovery.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.integrations.overpass import OverpassClient, OverpassPlace
from dispatchzero.integrations.wikidata import WikidataClient
from dispatchzero.models import Place, PlaceCategory, PlaceStatus, User, UserPlaceHistory
from dispatchzero.services.scoring import ScoreInput, score_place

_RE_ENTRY_DAYS = 90


async def discover_nearby(
    *,
    db: AsyncSession,
    redis: aioredis.Redis,
    user: User,
    lat: float,
    lng: float,
    radius_m: int,
    limit: int,
    categories: list[PlaceCategory] | None = None,
) -> list[dict[str, Any]]:
    """Find, persist, score, filter, and return nearby places for `user`."""
    cats = categories or list(PlaceCategory)

    overpass = OverpassClient(redis)
    wikidata = WikidataClient(redis)
    try:
        raw_places = await overpass.query_nearby(
            lat=lat, lng=lng, radius_m=radius_m, categories=cats
        )
        # Filter unnamed at the boundary — saves DB writes and downstream work.
        named = [p for p in raw_places if p.name]
        # Upsert into Place table, attaching enrichment along the way.
        stored: list[Place] = []
        for op in named:
            place = await _upsert_place(db, op, wikidata)
            stored.append(place)
        await db.commit()
    finally:
        await overpass.aclose()
        await wikidata.aclose()

    # Filter against user's recent history.
    cutoff = datetime.now(timezone.utc) - timedelta(days=_RE_ENTRY_DAYS)
    recent_completed_ids = set(
        (await db.execute(
            select(UserPlaceHistory.place_id).where(
                UserPlaceHistory.user_id == user.id,
                UserPlaceHistory.last_completed_at > cutoff,
            )
        )).scalars()
    )

    eligible = [
        p for p in stored
        if p.id not in recent_completed_ids and p.status == PlaceStatus.ACTIVE.value
    ]

    # Score each, sort descending, trim to limit.
    scored = sorted(
        eligible,
        key=lambda p: score_place(
            ScoreInput(
                name=p.name,
                description=p.description,
                has_wikidata=bool(p.wikidata_id),
                category=PlaceCategory(p.category),
                thumbs_up=p.location_thumbs_up,
                thumbs_down=p.location_thumbs_down,
            )
        ),
        reverse=True,
    )[:limit]

    return [_serialize_place(p) for p in scored]


async def _upsert_place(
    db: AsyncSession, op: OverpassPlace, wikidata: WikidataClient
) -> Place:
    # Pull description from Wikidata if the OSM tags carry a Q-ID.
    qid = op.tags.get("wikidata")
    description = await wikidata.get_description(qid) if qid else None

    # Upsert by (osm_type, osm_id). Use Postgres ON CONFLICT for idempotency.
    stmt = pg_insert(Place).values(
        id=uuid.uuid4(),
        osm_type=op.osm_type,
        osm_id=op.osm_id,
        name=op.name,
        category=op.category.value,
        coordinates=f"SRID=4326;POINT({op.lng} {op.lat})",
        tags=op.tags,
        description=description,
        wikidata_id=qid,
    ).on_conflict_do_update(
        index_elements=["osm_type", "osm_id"],
        set_={
            "name": op.name,
            "category": op.category.value,
            "tags": op.tags,
            "description": description,
            "wikidata_id": qid,
            "coordinates": f"SRID=4326;POINT({op.lng} {op.lat})",
        },
    ).returning(Place.id)

    result = await db.execute(stmt)
    place_id = result.scalar_one()

    # Re-fetch the full row for downstream use.
    place = (
        await db.execute(select(Place).where(Place.id == place_id))
    ).scalar_one()
    return place


def _serialize_place(p: Place) -> dict[str, Any]:
    return {
        "id": p.id,
        "osm_type": p.osm_type,
        "osm_id": p.osm_id,
        "name": p.name,
        "category": p.category,
        "description": p.description,
        "wikidata_id": p.wikidata_id,
        "thumbs_up": p.location_thumbs_up,
        "thumbs_down": p.location_thumbs_down,
    }
```

- [ ] **Step 7.3: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | grep -E "test_discovery|PASSED|FAILED" | tail -10
```

Expected: 4 passed.

- [ ] **Step 7.4: Commit**

```bash
git add src/dispatchzero/services/discovery.py tests/test_discovery.py
git commit -m "feat: discovery service orchestrating overpass+wikidata+scoring with 90-day re-entry"
```

---

### Task 8: HTTP route `GET /places/nearby`

**Files:**
- Create: `src/dispatchzero/schemas/places.py`
- Create: `src/dispatchzero/places/__init__.py`
- Create: `src/dispatchzero/places/routes.py`
- Modify: `src/dispatchzero/main.py` (mount router)
- Create: `tests/test_places_routes.py`

- [ ] **Step 8.1: Write failing tests**

Write to `tests/test_places_routes.py`:

```python
import httpx
import pytest
import respx

SIGNUP = {
    "callsign": "Hunter_01",
    "password": "long-enough-password",
    "adventure_style": "agency",
}


def _overpass_one(name: str = "Test Mural") -> dict:
    return {
        "elements": [
            {
                "type": "node",
                "id": 9001,
                "lat": 37.7749,
                "lon": -122.4194,
                "tags": {"name": name, "tourism": "artwork", "artwork_type": "mural"},
            }
        ]
    }


@pytest.mark.asyncio
async def test_nearby_requires_auth(client, db_session, redis_client):
    client.cookies.clear()
    r = await client.get("/places/nearby?lat=37.7749&lng=-122.4194")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_nearby_returns_places_for_authed_user(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP)
    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json=_overpass_one())
        )
        r = await client.get("/places/nearby?lat=37.7749&lng=-122.4194")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["name"] == "Test Mural"
    assert body[0]["category"] == "mural"


@pytest.mark.asyncio
async def test_nearby_clamps_radius(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP)
    # radius_m=999999 → clamped to 10000
    with respx.mock:
        route = respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json={"elements": []})
        )
        r = await client.get("/places/nearby?lat=37.7749&lng=-122.4194&radius_m=999999")
    assert r.status_code == 200
    body = route.calls.last.request.read().decode()
    assert "around:10000" in body


@pytest.mark.asyncio
async def test_nearby_rejects_invalid_lat_lng(client, db_session, redis_client):
    await client.post("/auth/signup", json=SIGNUP)
    r = await client.get("/places/nearby?lat=999&lng=-122.4194")
    assert r.status_code == 422
```

- [ ] **Step 8.2: Implement**

Write to `src/dispatchzero/schemas/places.py`:

```python
import uuid

from pydantic import BaseModel


class PlaceOut(BaseModel):
    id: uuid.UUID
    osm_type: str
    osm_id: int
    name: str | None
    category: str
    description: str | None
    wikidata_id: str | None
    thumbs_up: int
    thumbs_down: int
```

Write to `src/dispatchzero/places/__init__.py`:

```python
```
(empty)

Write to `src/dispatchzero/places/routes.py`:

```python
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.deps import current_user
from dispatchzero.config import Settings, get_settings
from dispatchzero.db import get_session
from dispatchzero.models import User
from dispatchzero.schemas.places import PlaceOut
from dispatchzero.services.discovery import discover_nearby

router = APIRouter(prefix="/places", tags=["places"])


async def _get_redis(
    settings: Annotated[Settings, Depends(get_settings)],
) -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


@router.get("/nearby", response_model=list[PlaceOut])
async def nearby(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[aioredis.Redis, Depends(_get_redis)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    radius_m: Annotated[int, Query(ge=100, le=10000)] = 2000,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict]:
    return await discover_nearby(
        db=db, redis=redis, user=user,
        lat=lat, lng=lng, radius_m=radius_m, limit=limit,
    )
```

- [ ] **Step 8.3: Mount the router**

In `src/dispatchzero/main.py`:

```python
from fastapi import FastAPI

from dispatchzero.auth.routes import router as auth_router
from dispatchzero.places.routes import router as places_router

app = FastAPI(title="Dispatch Zero")
app.include_router(auth_router)
app.include_router(places_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "dispatch-zero", "status": "operational"}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 8.4: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | tail -10
```

Expected: all tests pass. New: 4 places routes tests.

- [ ] **Step 8.5: Commit**

```bash
git add src/dispatchzero/schemas/places.py src/dispatchzero/places src/dispatchzero/main.py tests/test_places_routes.py
git commit -m "feat: GET /places/nearby endpoint with auth + radius/limit clamping"
```

---

### Task 9: Admin CLI tool for manual debugging

**Files:**
- Create: `src/dispatchzero/tools/__init__.py`
- Create: `src/dispatchzero/tools/discover_places.py`

(No tests — this is a one-shot operator tool. Exercised by Task 10's smoke run.)

- [ ] **Step 9.1: Implement**

Write to `src/dispatchzero/tools/__init__.py`:

```python
```
(empty)

Write to `src/dispatchzero/tools/discover_places.py`:

```python
"""One-shot CLI for manual place discovery debugging.

Usage (inside the app container on VPS 2):
    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app \\
        python -m dispatchzero.tools.discover_places \\
        --callsign smoketest --lat 37.7749 --lng -122.4194 --radius-m 1500
"""
import argparse
import asyncio

import redis.asyncio as aioredis
from sqlalchemy import select

from dispatchzero.config import get_settings
from dispatchzero.db import get_engine
from dispatchzero.models import User
from dispatchzero.services.discovery import discover_nearby
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--callsign", required=True)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lng", type=float, required=True)
    parser.add_argument("--radius-m", type=int, default=2000)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    settings = get_settings()
    engine = get_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.callsign_lower == args.callsign.lower()))
        ).scalar_one_or_none()
        if user is None:
            print(f"no user with callsign {args.callsign!r}")
            return
        results = await discover_nearby(
            db=db, redis=redis, user=user,
            lat=args.lat, lng=args.lng, radius_m=args.radius_m, limit=args.limit,
        )

    for r in results:
        print(f"{r['category']:10s} {r['name']!r:40s} osm:{r['osm_type']}/{r['osm_id']}")
    print(f"\n{len(results)} places")
    await redis.aclose()


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 9.2: Commit**

```bash
git add src/dispatchzero/tools
git commit -m "feat: CLI tool for manual discover_places debugging"
```

---

### Task 10: Deploy + curl-verify against real Nominatim/Overpass

- [ ] **Step 10.1: Deploy**

```bash
./deploy/deploy.sh
```

Expected: deploy succeeds, alembic upgrades to `0003`.

- [ ] **Step 10.2: Verify migration applied**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app alembic current"
```

Expected: `0003 (head)`.

- [ ] **Step 10.3: Curl a real signup → /places/nearby flow against prod**

Smoke-test coordinate: **the Garbage Goat, Spokane Riverfront Park** (`47.6605131, -117.4197590`). The Garbage Goat itself (OSM node `10558408202`, `tourism=artwork`) sits on the Centennial Trail in Riverpoint Village and will appear in the result set as a sculpture. A direct Overpass query around this point with a 2 km radius (run 2026-04-26 to validate the plan) returned ~104 raw OSM elements normalizing to ~68 named places across all five categories. Sample of what Task 10 will surface (top items per category):

| Category | Sample names found in 2 km of (47.6588, -117.4260) |
|---|---|
| **mural** (2) | Fish Eye View; Black Lives Matter |
| **sculpture** (23) | Abraham Lincoln; Expo 74 Butterfly; The Joy of Running Together; Footsteps to the Future; Centennial Sculpture; Al's Cube |
| **memorial** (7) | Vietnam Veterans Memorial; Michael P Anderson; Milk Bottle; Historic Chinatown |
| **historic** (30) | Woman's Club of Spokane; Spokane Fire Station #9; Graham House; Monroe House; Hanauer-Cook House |
| **viewpoint** (6) | Lower Falls; Inspiration Point; Cliff Park Viewpoint; Edwidge Wilson Park Viewpoint |

```bash
COOKIES=$(mktemp)

# Signup
curl -sS -c "$COOKIES" -X POST https://dispatchzero.ataary.com/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"callsign":"smoketest_p3","password":"smoketest-very-long-password","adventure_style":"agency"}'
echo

# Discover nearby — centered on the Garbage Goat, Spokane Riverfront Park
curl -sS -b "$COOKIES" \
  "https://dispatchzero.ataary.com/places/nearby?lat=47.6605131&lng=-117.4197590&radius_m=2000&limit=10" \
  | python3 -m json.tool
echo

# Cache hit verification — second call should be much faster
echo "--- second call (warm cache) ---"
time curl -sS -b "$COOKIES" \
  "https://dispatchzero.ataary.com/places/nearby?lat=47.6605131&lng=-117.4197590&radius_m=2000&limit=10" \
  > /dev/null

rm -f "$COOKIES"
```

Expected:
- Signup returns the user JSON.
- /places/nearby returns up to 10 ranked places drawn from the ~68-place Spokane downtown pool. **The Garbage Goat itself should appear** as a sculpture; murals and sculptures should rank near the top of the list (category bonus).
- Second call is sub-200ms (Overpass response cached for 7 days; Wikidata enrichment cached for 30 days).

- [ ] **Step 10.4: Inspect what landed in the `places` table**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -c 'SELECT category, name, wikidata_id IS NOT NULL AS has_wd FROM places ORDER BY name LIMIT 20;'"
```

Expected: a populated table with real OSM-derived rows.

- [ ] **Step 10.5: Run the CLI tool end-to-end**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app python -m dispatchzero.tools.discover_places --callsign smoketest_p3 --lat 47.6605131 --lng -117.4197590 --radius-m 1500"
```

Expected: prints multiple Spokane places with category labels and a count.

- [ ] **Step 10.6: Clean up the smoke-test user**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -c \"DELETE FROM user_place_history WHERE user_id IN (SELECT id FROM users WHERE callsign_lower = 'smoketest_p3'); DELETE FROM users WHERE callsign_lower = 'smoketest_p3';\""
```

(Don't delete from `places` — the cached OSM data is real and shared across users; future users benefit from the warm cache.)

- [ ] **Step 10.7: Confirm Paperclip and resources still healthy**

```bash
ssh root@89.167.39.152 "systemctl is-active paperclip.service && free -h && df -h /"
```

Expected: `active`, RAM available > 1.5 GB, disk used < 85%.

---

## Phase 3 — Definition of Done

- All tests pass via `./deploy/test.sh`.
- Production smoke (signup → /places/nearby) returns ≥1 real place from Overpass for a known urban coordinate.
- Second call to the same coordinate is sub-200ms (proves Redis cache works).
- Migration `0003` applied; `places` and `user_place_history` tables exist with PostGIS-typed `coordinates`.
- The CLI tool runs cleanly inside the app container.
- Paperclip restart count unchanged.
- `httpx` and `respx` deps in `uv.lock`.

---

## Critical Files To Be Created In Phase 3

| File | Purpose |
|---|---|
| `src/dispatchzero/integrations/_throttle.py` | Async min-interval throttle for Nominatim |
| `src/dispatchzero/integrations/_cache.py` | Redis JSON cache helper |
| `src/dispatchzero/integrations/nominatim.py` | Geocoding wrapper |
| `src/dispatchzero/integrations/overpass.py` | OSM place query wrapper |
| `src/dispatchzero/integrations/wikidata.py` | Description enrichment |
| `src/dispatchzero/models/place.py` | Place model (PostGIS Geography) |
| `src/dispatchzero/models/user_place_history.py` | Per-user 90-day completion log |
| `src/dispatchzero/services/scoring.py` | Quest-worthiness score (pure function) |
| `src/dispatchzero/services/discovery.py` | Pipeline orchestrator |
| `src/dispatchzero/schemas/places.py` | PlaceOut |
| `src/dispatchzero/places/routes.py` | GET /places/nearby |
| `src/dispatchzero/tools/discover_places.py` | CLI for manual debug |
| `alembic/versions/0003_places_and_history.py` | Migration |

---

## Open Decisions (default in plan, override before starting)

| Decision | Default | Where to change |
|---|---|---|
| Default search radius | 2 km | `places/routes.py` query parameter default |
| Result limit cap | 50 | `places/routes.py` `Query(le=50)` |
| Scoring weights | See `scoring.py` | Tune after Phase 5 produces real ratings |
| Wikidata description language | English only | `integrations/wikidata.py` `languages` param |
| Overpass instance | `overpass-api.de` | `integrations/overpass.py` `_BASE_URL` |
| Re-entry window | 90 days | `services/discovery.py` `_RE_ENTRY_DAYS` |
| Category bonus weights | See `_CATEGORY_BONUS` in `scoring.py` | Adjust after real-world data |
| Should Wikipedia (full article) replace Wikidata description? | No, Wikidata only | Add separate Wikipedia client in Phase 4 if needed for richer mission writing |

---

## What Comes Next After Phase 3

Phase 4 — Mission generation. With place discovery returning candidates, Phase 4 picks one (library hit if available, fresh Ollama call otherwise) and generates the dispatch + briefing text in the user's chosen style. The Phase 4 plan will be written using this same skill at the end of Phase 3.

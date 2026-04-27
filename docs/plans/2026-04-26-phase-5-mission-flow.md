# Phase 5: Mission Flow API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A logged-in client can drive a complete mission via the API. Phase 3 (place discovery) and Phase 4 (mission generation) get wired into a single end-to-end lifecycle: request → accept → capture (photo + GPS + EXIF) → debrief → rate. The endpoint set is the contract the Phase 6+ frontend will consume.

**Architecture:** Five thin layers, plus the `Completion` row.

1. **Photo helpers** (`services/photo.py`) — pure functions: read EXIF DateTimeOriginal, compute freshness delta, Haversine distance, resize+strip+save thumbnail. Each fully unit-tested with synthetic JPEGs (Pillow + small `piexif` helper or hand-crafted EXIF bytes).
2. **Verification policy** (`services/verification.py`) — combines GPS-radius check + EXIF-freshness check into a single `verify_capture()` decision. Pure function over inputs. Per-category radius lookup. Returns `(verified: bool, fail_reason: str | None, distance_m: float, exif_delta_s: int | None)`.
3. **Progression** (`services/progression.py`) — XP table per category, weekly-mission-count update logic (timezone-aware, week starts Monday UTC). Pure functions where possible.
4. **Mission lifecycle service** (`services/mission_flow.py`) — orchestrates the four state transitions: `request`, `accept`, `capture`, `rate`. Calls into Phase 3 discovery + Phase 4 generation as needed. Writes `Completion` and `UserPlaceHistory` rows. Updates aggregate counters on `Place` and `Mission`.
5. **HTTP routes** (`missions/routes.py` extension) — four new endpoints, all auth-required.

**Tech additions:** `Pillow` (image processing), `python-multipart` (FastAPI multipart form parsing — required runtime dep when using `UploadFile`/`Form()`). Both stable, single-purpose libraries.

**Decision defaults (override before starting):**

| Decision | Default | Why |
|---|---|---|
| GPS radius per category | mural 60m, sculpture 40m, memorial 50m, historic 80m, viewpoint 100m | Urban GPS drift floor is ~30m; calibrated by feature size |
| EXIF freshness window | 600s (10 min) | Per spec; absorbs slow connectivity, GPS settling, walk-to-signal |
| XP per completion | base 10 + category bonus (mural +5, sculpture +3, memorial +3, historic +2, viewpoint +1) | Simple, tunable from real data later |
| Weekly count reset | Monday 00:00 UTC | Simple, no per-user timezone in v1 |
| Auto-retire trigger | ≥3 of last 5 location ratings are thumbs-down → `place.status='flagged'` | Per spec |
| Mission regen trigger | A single mission thumbs-down → `mission.status='needs_regen'` (so next request for this place+style generates fresh) | Per spec |
| Photo storage path | `/uploads/completions/{user_id}/{completion_id}.jpg` (host bind-mount: `/opt/dispatchzero/uploads`) | Per spec |
| Image processing | Resize to fit 600×600, strip EXIF, JPEG q70 | Per spec |
| `accept` endpoint | No-op success (no DB write) for v1 | Simpler; analytics can be added later via a dedicated events table |
| `request` endpoint | Combines /places/nearby + /missions/generate into one call | Better UX than client orchestrating two requests |
| Auth-required photo serving | Skipped in Phase 5 — added in Phase 9 (mission cards) when public access is needed | Photos are personal and not yet displayed anywhere user-facing |
| Drop placeholder coords from prompt | YES — fix the "grid 0.00000,0.00000" leak from Phase 4 in this phase | Trivial change to `mission_prompts.py` |

**Repo layout deltas after this phase:**

```
dispatch-zero/
├── src/dispatchzero/
│   ├── (existing)
│   ├── services/
│   │   ├── (existing)
│   │   ├── photo.py                   # NEW — EXIF, Haversine, resize/strip
│   │   ├── verification.py            # NEW — combined verify_capture()
│   │   ├── progression.py             # NEW — XP table + weekly count
│   │   └── mission_flow.py            # NEW — request/accept/capture/rate orchestrator
│   ├── schemas/
│   │   ├── (existing)
│   │   └── completions.py             # NEW — RequestIn, RateIn, CompletionOut, DebriefOut
│   ├── models/
│   │   ├── (existing)
│   │   └── completion.py              # NEW
│   └── missions/
│       └── routes.py                  # MODIFIED — adds /request, /{id}/accept, /{id}/capture, /{id}/rate
├── alembic/versions/
│   └── 0005_completions.py            # NEW
├── docker-compose.prod.yml            # MODIFIED — adds /opt/dispatchzero/uploads bind-mount
└── tests/
    ├── (existing)
    ├── test_photo.py                  # NEW
    ├── test_verification.py           # NEW
    ├── test_progression.py            # NEW
    ├── test_mission_flow_service.py   # NEW (full orchestration)
    └── test_missions_flow_routes.py   # NEW (HTTP integration)
```

---

### Task 1: Add deps + Settings extensions

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/dispatchzero/config.py`
- Create: `tests/test_config_completion.py`

- [ ] **Step 1.1: Add deps**

In `pyproject.toml` `dependencies`:

```toml
    "Pillow>=11.0",
    "python-multipart>=0.0.20",
```

In `[dependency-groups].dev`:

```toml
    "piexif>=1.1.3",  # for crafting test JPEGs with controlled EXIF
```

```bash
uv sync
```

- [ ] **Step 1.2: Write failing test for new Settings fields**

Write to `tests/test_config_completion.py`:

```python
from dispatchzero.config import Settings


def test_completion_settings_have_sensible_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.delenv("PHOTO_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("EXIF_FRESHNESS_WINDOW_SECONDS", raising=False)
    s = Settings()
    assert s.photo_upload_dir == "/uploads"
    assert s.exif_freshness_window_seconds == 600  # 10 min
    assert s.photo_max_dimension == 600
    assert s.photo_jpeg_quality == 70
```

- [ ] **Step 1.3: Run, confirm fail**

```bash
./deploy/test.sh 2>&1 | grep -E "test_config_completion|FAILED|PASSED" | tail -5
```

- [ ] **Step 1.4: Implement**

In `src/dispatchzero/config.py`, append to `Settings`:

```python
    # Photo capture and verification
    photo_upload_dir: str = "/uploads"
    photo_max_dimension: int = 600
    photo_jpeg_quality: int = 70
    exif_freshness_window_seconds: int = 600  # 10 min
```

- [ ] **Step 1.5: Run, confirm pass + commit**

```bash
./deploy/test.sh 2>&1 | tail -5
git add pyproject.toml uv.lock src/dispatchzero/config.py tests/test_config_completion.py
git commit -m "feat: add Pillow + python-multipart + photo/EXIF settings"
```

---

### Task 2: Completion model + migration 0005

**Files:**
- Create: `src/dispatchzero/models/completion.py`
- Modify: `src/dispatchzero/models/__init__.py`
- Create: `alembic/versions/0005_completions.py`

- [ ] **Step 2.1: Create the Completion model**

Write to `src/dispatchzero/models/completion.py`:

```python
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class LocationReason(StrEnum):
    GONE = "gone"
    NOT_FOUND = "not_found"
    INACCESSIBLE = "inaccessible"
    UNSAFE = "unsafe"


class Completion(Base):
    __tablename__ = "completions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("places.id", ondelete="CASCADE"),
        nullable=False,
    )

    photo_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    capture_lat: Mapped[float] = mapped_column(Float, nullable=False)
    capture_lng: Mapped[float] = mapped_column(Float, nullable=False)
    capture_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)

    had_exif: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    exif_datetime_delta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    had_exif_gps: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    location_rating: Mapped[str | None] = mapped_column(String(8), nullable=True)  # up|down|null
    mission_rating: Mapped[str | None] = mapped_column(String(8), nullable=True)
    location_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)

    xp_awarded: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 2.2: Register in `models/__init__.py`**

```python
from dispatchzero.models.base import Base
from dispatchzero.models.completion import Completion, LocationReason
from dispatchzero.models.mission import Mission, MissionStatus
from dispatchzero.models.mission_stop import MissionStop
from dispatchzero.models.place import Place, PlaceCategory, PlaceStatus
from dispatchzero.models.user import AdventureStyle, User
from dispatchzero.models.user_place_history import UserPlaceHistory

__all__ = [
    "AdventureStyle", "Base", "Completion", "LocationReason",
    "Mission", "MissionStatus", "MissionStop",
    "Place", "PlaceCategory", "PlaceStatus",
    "User", "UserPlaceHistory",
]
```

- [ ] **Step 2.3: Write migration 0005 (one statement per `op.execute()`)**

Write to `alembic/versions/0005_completions.py`:

```python
"""add completions table

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-26
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE completions (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            mission_id UUID NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
            place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
            photo_url VARCHAR(400),
            capture_lat DOUBLE PRECISION NOT NULL,
            capture_lng DOUBLE PRECISION NOT NULL,
            capture_accuracy_m DOUBLE PRECISION,
            had_exif BOOLEAN NOT NULL DEFAULT FALSE,
            exif_datetime_delta_seconds INTEGER,
            had_exif_gps BOOLEAN NOT NULL DEFAULT FALSE,
            verified BOOLEAN NOT NULL DEFAULT FALSE,
            location_rating VARCHAR(8),
            mission_rating VARCHAR(8),
            location_reason VARCHAR(16),
            xp_awarded INTEGER NOT NULL DEFAULT 0,
            completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_completions_user_completed ON completions (user_id, completed_at DESC)")
    op.execute("CREATE INDEX ix_completions_place ON completions (place_id, completed_at DESC)")
    op.execute("CREATE INDEX ix_completions_mission ON completions (mission_id, completed_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS completions")
```

- [ ] **Step 2.4: Run tests + commit**

```bash
./deploy/test.sh 2>&1 | tail -5
git add src/dispatchzero/models alembic/versions/0005_completions.py
git commit -m "feat: add Completion model and migration 0005"
```

---

### Task 3: Photo helpers (TDD with synthetic JPEGs)

**Files:**
- Create: `src/dispatchzero/services/photo.py`
- Create: `tests/test_photo.py`

- [ ] **Step 3.1: Write failing tests**

Write to `tests/test_photo.py`:

```python
import io
import math
from datetime import datetime, timedelta, timezone

import piexif
import pytest
from PIL import Image

from dispatchzero.services.photo import (
    haversine_distance_m,
    make_test_jpeg,
    read_exif_datetime,
    read_exif_has_gps,
    save_thumbnail,
)


# ---- helper for tests ----

def _jpeg_with_exif(dt: datetime | None, with_gps: bool = False) -> bytes:
    img = Image.new("RGB", (1200, 1200), color=(80, 90, 100))
    exif_dict: dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    if dt is not None:
        ts = dt.strftime("%Y:%m:%d %H:%M:%S")
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = ts.encode()
    if with_gps:
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = ((47, 1), (39, 1), (37, 1))
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = b"N"
    exif_bytes = piexif.dump(exif_dict)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_bytes)
    return buf.getvalue()


# ---- haversine ----

def test_haversine_zero_distance_for_same_point():
    d = haversine_distance_m(47.6605, -117.4198, 47.6605, -117.4198)
    assert d < 0.5


def test_haversine_known_distance_one_degree_lat():
    # 1 degree of latitude ≈ 111 km, regardless of longitude
    d = haversine_distance_m(47.0, -117.0, 48.0, -117.0)
    assert 110_000 < d < 112_000


def test_haversine_short_distance_within_spokane():
    # Garbage Goat to a point ~150 m east
    d = haversine_distance_m(47.6605, -117.4198, 47.6605, -117.4178)
    assert 140 < d < 160


# ---- EXIF reading ----

def test_read_exif_datetime_returns_aware_datetime():
    target = datetime(2026, 4, 26, 14, 30, 15, tzinfo=timezone.utc)
    raw = _jpeg_with_exif(target)
    parsed = read_exif_datetime(raw)
    # Compare as naive UTC since EXIF lacks tz info; we treat as UTC by convention
    assert parsed is not None
    assert parsed.year == 2026 and parsed.month == 4 and parsed.day == 26
    assert parsed.hour == 14 and parsed.minute == 30 and parsed.second == 15


def test_read_exif_datetime_returns_none_when_missing():
    raw = _jpeg_with_exif(None)
    assert read_exif_datetime(raw) is None


def test_read_exif_datetime_returns_none_for_garbage_input():
    assert read_exif_datetime(b"not a jpeg") is None


def test_read_exif_has_gps_true_when_gps_present():
    raw = _jpeg_with_exif(datetime.utcnow(), with_gps=True)
    assert read_exif_has_gps(raw) is True


def test_read_exif_has_gps_false_when_absent():
    raw = _jpeg_with_exif(datetime.utcnow(), with_gps=False)
    assert read_exif_has_gps(raw) is False


# ---- thumbnail save ----

def test_save_thumbnail_resizes_and_strips_exif(tmp_path):
    raw = _jpeg_with_exif(datetime.utcnow(), with_gps=True)
    out = tmp_path / "out.jpg"
    save_thumbnail(raw, out, max_dim=600, quality=70)
    assert out.exists()
    written = out.read_bytes()
    img = Image.open(io.BytesIO(written))
    assert max(img.size) <= 600
    # No EXIF in re-encoded thumbnail
    assert read_exif_datetime(written) is None
    assert read_exif_has_gps(written) is False


def test_save_thumbnail_creates_parent_dirs(tmp_path):
    raw = _jpeg_with_exif(datetime.utcnow())
    nested = tmp_path / "a" / "b" / "c" / "out.jpg"
    save_thumbnail(raw, nested, max_dim=600, quality=70)
    assert nested.exists()


# ---- make_test_jpeg (helper exported for downstream test reuse) ----

def test_make_test_jpeg_round_trips_datetime():
    dt = datetime(2026, 4, 26, 12, 0, 0)
    raw = make_test_jpeg(captured_at=dt)
    assert read_exif_datetime(raw).hour == 12
```

- [ ] **Step 3.2: Run, confirm fail**

```bash
./deploy/test.sh 2>&1 | grep -E "test_photo|FAILED|PASSED" | tail -8
```

- [ ] **Step 3.3: Implement**

Write to `src/dispatchzero/services/photo.py`:

```python
import io
import math
from datetime import datetime
from pathlib import Path

import piexif
from PIL import Image, ImageOps


def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in meters."""
    R = 6_371_000.0  # Earth radius in m
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def read_exif_datetime(raw_bytes: bytes) -> datetime | None:
    """Return EXIF DateTimeOriginal as a naive datetime (UTC by convention), or None."""
    try:
        exif = piexif.load(raw_bytes)
    except Exception:
        return None
    raw = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
    if raw is None:
        return None
    try:
        s = raw.decode() if isinstance(raw, bytes) else str(raw)
        return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None


def read_exif_has_gps(raw_bytes: bytes) -> bool:
    """Whether the EXIF carries any GPS tag."""
    try:
        exif = piexif.load(raw_bytes)
    except Exception:
        return False
    gps = exif.get("GPS", {})
    return bool(gps)


def save_thumbnail(
    raw_bytes: bytes,
    path: Path,
    *,
    max_dim: int = 600,
    quality: int = 70,
) -> None:
    """Decode, auto-orient, resize to fit (max_dim x max_dim), strip ALL EXIF, save JPEG."""
    img = Image.open(io.BytesIO(raw_bytes))
    img = ImageOps.exif_transpose(img)  # honor orientation BEFORE stripping EXIF
    img.thumbnail((max_dim, max_dim))
    if img.mode != "RGB":
        img = img.convert("RGB")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="JPEG", quality=quality, optimize=True, exif=b"")


def make_test_jpeg(
    *,
    captured_at: datetime | None = None,
    size: tuple[int, int] = (1200, 1200),
    color: tuple[int, int, int] = (80, 90, 100),
) -> bytes:
    """Helper used by downstream tests — synthesize a JPEG with controlled EXIF."""
    img = Image.new("RGB", size, color=color)
    exif_dict: dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    if captured_at is not None:
        ts = captured_at.strftime("%Y:%m:%d %H:%M:%S")
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = ts.encode()
    exif_bytes = piexif.dump(exif_dict)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_bytes)
    return buf.getvalue()
```

- [ ] **Step 3.4: Run, confirm pass + commit**

```bash
./deploy/test.sh 2>&1 | tail -5
git add src/dispatchzero/services/photo.py tests/test_photo.py
git commit -m "feat: photo helpers (Haversine, EXIF read, resize+strip thumbnail)"
```

---

### Task 4: Verification policy (TDD)

**Files:**
- Create: `src/dispatchzero/services/verification.py`
- Create: `tests/test_verification.py`

- [ ] **Step 4.1: Write failing tests**

Write to `tests/test_verification.py`:

```python
from datetime import datetime, timedelta, timezone

from dispatchzero.models import PlaceCategory
from dispatchzero.services.photo import make_test_jpeg
from dispatchzero.services.verification import (
    RADIUS_M_BY_CATEGORY,
    VerificationResult,
    verify_capture,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC


def test_verify_passes_for_in_radius_fresh_photo():
    raw = make_test_jpeg(captured_at=_now_utc())
    result = verify_capture(
        raw_bytes=raw,
        capture_lat=47.6605,
        capture_lng=-117.4198,
        target_lat=47.6605,
        target_lng=-117.4198,
        category=PlaceCategory.SCULPTURE,
        freshness_window_seconds=600,
    )
    assert result.verified is True
    assert result.fail_reason is None
    assert result.distance_m < 1.0
    assert result.exif_delta_seconds is not None and result.exif_delta_seconds < 5


def test_verify_fails_when_outside_radius():
    raw = make_test_jpeg(captured_at=_now_utc())
    result = verify_capture(
        raw_bytes=raw,
        capture_lat=47.6605, capture_lng=-117.4178,  # ~150m east of target
        target_lat=47.6605, target_lng=-117.4198,
        category=PlaceCategory.SCULPTURE,  # 40m radius
        freshness_window_seconds=600,
    )
    assert result.verified is False
    assert result.fail_reason == "out_of_radius"
    assert result.distance_m > 100


def test_verify_fails_for_stale_exif():
    old = _now_utc() - timedelta(hours=2)
    raw = make_test_jpeg(captured_at=old)
    result = verify_capture(
        raw_bytes=raw,
        capture_lat=47.6605, capture_lng=-117.4198,
        target_lat=47.6605, target_lng=-117.4198,
        category=PlaceCategory.SCULPTURE,
        freshness_window_seconds=600,
    )
    assert result.verified is False
    assert result.fail_reason == "stale_capture"


def test_verify_fails_when_exif_missing_entirely():
    raw = make_test_jpeg(captured_at=None)  # no EXIF
    result = verify_capture(
        raw_bytes=raw,
        capture_lat=47.6605, capture_lng=-117.4198,
        target_lat=47.6605, target_lng=-117.4198,
        category=PlaceCategory.SCULPTURE,
        freshness_window_seconds=600,
    )
    assert result.verified is False
    assert result.fail_reason == "no_exif"


def test_per_category_radius_lookup():
    assert RADIUS_M_BY_CATEGORY[PlaceCategory.SCULPTURE] == 40
    assert RADIUS_M_BY_CATEGORY[PlaceCategory.MURAL] == 60
    assert RADIUS_M_BY_CATEGORY[PlaceCategory.MEMORIAL] == 50
    assert RADIUS_M_BY_CATEGORY[PlaceCategory.HISTORIC] == 80
    assert RADIUS_M_BY_CATEGORY[PlaceCategory.VIEWPOINT] == 100
```

- [ ] **Step 4.2: Implement**

Write to `src/dispatchzero/services/verification.py`:

```python
from dataclasses import dataclass
from datetime import datetime

from dispatchzero.models import PlaceCategory
from dispatchzero.services.photo import (
    haversine_distance_m,
    read_exif_datetime,
    read_exif_has_gps,
)

RADIUS_M_BY_CATEGORY: dict[PlaceCategory, float] = {
    PlaceCategory.MURAL: 60,
    PlaceCategory.SCULPTURE: 40,
    PlaceCategory.MEMORIAL: 50,
    PlaceCategory.HISTORIC: 80,
    PlaceCategory.VIEWPOINT: 100,
}


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    fail_reason: str | None  # 'out_of_radius' | 'no_exif' | 'stale_capture' | None
    distance_m: float
    exif_delta_seconds: int | None
    had_exif: bool
    had_exif_gps: bool


def verify_capture(
    *,
    raw_bytes: bytes,
    capture_lat: float,
    capture_lng: float,
    target_lat: float,
    target_lng: float,
    category: PlaceCategory,
    freshness_window_seconds: int = 600,
    now: datetime | None = None,
) -> VerificationResult:
    """Apply GPS-radius + EXIF-freshness gates. Returns a structured decision."""
    distance_m = haversine_distance_m(capture_lat, capture_lng, target_lat, target_lng)
    exif_dt = read_exif_datetime(raw_bytes)
    had_exif_gps = read_exif_has_gps(raw_bytes)
    had_exif = exif_dt is not None or had_exif_gps

    radius = RADIUS_M_BY_CATEGORY.get(category, 60)

    # 1) GPS gate (cheap, deterministic)
    if distance_m > radius:
        return VerificationResult(
            verified=False, fail_reason="out_of_radius",
            distance_m=distance_m, exif_delta_seconds=None,
            had_exif=had_exif, had_exif_gps=had_exif_gps,
        )

    # 2) Freshness gate
    if exif_dt is None:
        return VerificationResult(
            verified=False, fail_reason="no_exif",
            distance_m=distance_m, exif_delta_seconds=None,
            had_exif=had_exif, had_exif_gps=had_exif_gps,
        )
    now_naive = (now or datetime.utcnow()).replace(tzinfo=None)
    delta = int((now_naive - exif_dt).total_seconds())
    if delta < 0 or delta > freshness_window_seconds:
        return VerificationResult(
            verified=False, fail_reason="stale_capture",
            distance_m=distance_m, exif_delta_seconds=delta,
            had_exif=had_exif, had_exif_gps=had_exif_gps,
        )

    return VerificationResult(
        verified=True, fail_reason=None,
        distance_m=distance_m, exif_delta_seconds=delta,
        had_exif=had_exif, had_exif_gps=had_exif_gps,
    )
```

- [ ] **Step 4.3: Run + commit**

```bash
./deploy/test.sh 2>&1 | tail -5
git add src/dispatchzero/services/verification.py tests/test_verification.py
git commit -m "feat: verification policy (GPS radius + EXIF freshness, per-category)"
```

---

### Task 5: Progression (XP table + weekly counter, TDD)

**Files:**
- Create: `src/dispatchzero/services/progression.py`
- Create: `tests/test_progression.py`

- [ ] **Step 5.1: Write failing tests**

Write to `tests/test_progression.py`:

```python
from datetime import datetime, timedelta, timezone

from dispatchzero.models import PlaceCategory
from dispatchzero.services.progression import (
    XP_BY_CATEGORY,
    week_start_utc,
    xp_for_completion,
)


def test_xp_table_per_category():
    assert xp_for_completion(PlaceCategory.MURAL) == 15
    assert xp_for_completion(PlaceCategory.SCULPTURE) == 13
    assert xp_for_completion(PlaceCategory.MEMORIAL) == 13
    assert xp_for_completion(PlaceCategory.HISTORIC) == 12
    assert xp_for_completion(PlaceCategory.VIEWPOINT) == 11


def test_xp_each_category_at_least_base_10():
    for cat in PlaceCategory:
        assert xp_for_completion(cat) >= 10


def test_week_start_utc_returns_monday_midnight_for_a_wednesday():
    wednesday = datetime(2026, 4, 29, 14, 30, 0, tzinfo=timezone.utc)
    monday = week_start_utc(wednesday)
    assert monday.weekday() == 0
    assert monday.hour == 0 and monday.minute == 0 and monday.second == 0
    assert (wednesday - monday).days == 2


def test_week_start_utc_returns_same_day_for_a_monday_morning():
    monday_am = datetime(2026, 4, 27, 6, 0, 0, tzinfo=timezone.utc)
    start = week_start_utc(monday_am)
    assert start.weekday() == 0
    assert start.hour == 0
    assert (monday_am - start).total_seconds() == 6 * 3600
```

- [ ] **Step 5.2: Implement**

Write to `src/dispatchzero/services/progression.py`:

```python
from datetime import datetime, timedelta, timezone

from dispatchzero.models import PlaceCategory

_BASE_XP = 10
_BONUS: dict[PlaceCategory, int] = {
    PlaceCategory.MURAL: 5,
    PlaceCategory.SCULPTURE: 3,
    PlaceCategory.MEMORIAL: 3,
    PlaceCategory.HISTORIC: 2,
    PlaceCategory.VIEWPOINT: 1,
}

XP_BY_CATEGORY: dict[PlaceCategory, int] = {
    cat: _BASE_XP + bonus for cat, bonus in _BONUS.items()
}


def xp_for_completion(category: PlaceCategory) -> int:
    return XP_BY_CATEGORY.get(category, _BASE_XP)


def week_start_utc(now: datetime) -> datetime:
    """Return Monday 00:00 UTC of the week containing `now`."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)
```

- [ ] **Step 5.3: Run + commit**

```bash
./deploy/test.sh 2>&1 | tail -5
git add src/dispatchzero/services/progression.py tests/test_progression.py
git commit -m "feat: progression helpers (XP table + UTC week-start)"
```

---

### Task 6: Drop placeholder coords from mission prompt (Phase 4 polish)

**Files:**
- Modify: `src/dispatchzero/services/mission_prompts.py`
- Modify: `src/dispatchzero/services/missions.py`
- Modify: `tests/test_mission_prompts.py`

- [ ] **Step 6.1: Update prompt builder to drop coords entirely**

In `src/dispatchzero/services/mission_prompts.py`, change `build_mission_prompt`:

- Remove `place_lat` and `place_lng` parameters from the signature.
- Remove the line `at coordinates {place_lat:.5f}, {place_lng:.5f}` from the user message — replace with just `Target: {place_name} (a {place_category}).{description_line}`.

- [ ] **Step 6.2: Update the caller**

In `src/dispatchzero/services/missions.py`, drop `place_lat=0.0, place_lng=0.0` args from the `build_mission_prompt(...)` call.

- [ ] **Step 6.3: Update the prompt tests**

In `tests/test_mission_prompts.py`, remove `place_lat` and `place_lng` from the `_ctx()` helper and from any direct call.

- [ ] **Step 6.4: Run + commit**

```bash
./deploy/test.sh 2>&1 | tail -5
git add src/dispatchzero/services/mission_prompts.py src/dispatchzero/services/missions.py tests/test_mission_prompts.py
git commit -m "fix: drop placeholder coordinates from mission prompt (Phase 4 leak)"
```

---

### Task 7: Mission flow service (orchestrator, TDD)

**Files:**
- Create: `src/dispatchzero/services/mission_flow.py`
- Create: `tests/test_mission_flow_service.py`

This is the heart of Phase 5 — the four-state orchestrator (`request`, `accept`, `capture`, `rate`).

- [ ] **Step 7.1: Write failing tests**

Write to `tests/test_mission_flow_service.py`:

```python
import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.models import (
    Completion, Mission, Place, PlaceStatus, User, UserPlaceHistory,
)
from dispatchzero.services.mission_flow import (
    CaptureFailedError,
    capture_mission,
    rate_completion,
)
from dispatchzero.services.photo import make_test_jpeg


async def _seed(db: AsyncSession) -> tuple[User, Place, Mission]:
    user = User(
        callsign="Tester", callsign_lower="tester", password_hash="x",
        adventure_style="agency",
    )
    place = Place(
        osm_type="node", osm_id=1, name="Test Sculpture", category="sculpture",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)", tags={},
    )
    db.add_all([user, place])
    await db.commit()
    await db.refresh(user); await db.refresh(place)
    mission = Mission(
        place_id=place.id, adventure_style="agency",
        dispatch_summary="x", briefing_text="y",
    )
    db.add(mission)
    await db.commit()
    await db.refresh(mission)
    return user, place, mission


@pytest.mark.asyncio
async def test_capture_happy_path_persists_completion_and_awards_xp(
    db_session, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user, place, mission = await _seed(db_session)

    raw = make_test_jpeg(captured_at=datetime.utcnow())
    completion = await capture_mission(
        db=db_session, user=user, mission=mission, place=place,
        raw_photo=raw,
        capture_lat=47.6605, capture_lng=-117.4198, capture_accuracy_m=8.0,
    )

    assert completion.verified is True
    assert completion.xp_awarded == 13  # sculpture: 10 + 3
    assert completion.had_exif is True
    # XP added to user
    refreshed = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert refreshed.xp == 13
    assert refreshed.missions_this_week == 1
    # Place added to user_place_history
    history = (await db_session.execute(
        select(UserPlaceHistory).where(UserPlaceHistory.user_id == user.id)
    )).scalar_one()
    assert history.place_id == place.id
    # Photo file exists on disk
    assert completion.photo_url is not None


@pytest.mark.asyncio
async def test_capture_rejects_out_of_radius(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user, place, mission = await _seed(db_session)

    raw = make_test_jpeg(captured_at=datetime.utcnow())
    with pytest.raises(CaptureFailedError, match="out_of_radius"):
        await capture_mission(
            db=db_session, user=user, mission=mission, place=place,
            raw_photo=raw,
            capture_lat=47.6700, capture_lng=-117.4100, capture_accuracy_m=8.0,
        )
    # No completion persisted
    rows = (await db_session.execute(select(Completion))).scalars().all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_capture_rejects_stale_exif(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user, place, mission = await _seed(db_session)
    from datetime import timedelta
    old = datetime.utcnow() - timedelta(hours=2)
    raw = make_test_jpeg(captured_at=old)
    with pytest.raises(CaptureFailedError, match="stale"):
        await capture_mission(
            db=db_session, user=user, mission=mission, place=place,
            raw_photo=raw,
            capture_lat=47.6605, capture_lng=-117.4198, capture_accuracy_m=8.0,
        )


@pytest.mark.asyncio
async def test_rate_updates_aggregates_on_place_and_mission(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user, place, mission = await _seed(db_session)
    raw = make_test_jpeg(captured_at=datetime.utcnow())
    completion = await capture_mission(
        db=db_session, user=user, mission=mission, place=place,
        raw_photo=raw,
        capture_lat=47.6605, capture_lng=-117.4198, capture_accuracy_m=8.0,
    )

    await rate_completion(
        db=db_session, user=user, completion=completion,
        location_rating="up", mission_rating="down",
        location_reason=None,
    )
    refreshed_place = (await db_session.execute(select(Place).where(Place.id == place.id))).scalar_one()
    assert refreshed_place.location_thumbs_up == 1
    assert refreshed_place.location_thumbs_down == 0
    refreshed_mission = (await db_session.execute(select(Mission).where(Mission.id == mission.id))).scalar_one()
    assert refreshed_mission.mission_thumbs_down == 1
    # Single thumbs-down → flagged for regen
    assert refreshed_mission.status == "needs_regen"


@pytest.mark.asyncio
async def test_rate_three_negatives_in_last_five_flags_place(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    user, place, mission = await _seed(db_session)
    # Manually seed 5 completions, 3 of which are thumbs_down
    from dispatchzero.services.mission_flow import _apply_auto_retire  # internal helper
    place.location_thumbs_up = 2
    place.location_thumbs_down = 3
    db_session.add(place)
    await db_session.commit()
    # Simulate 5 prior ratings — 3 down in the last 5
    for i, rating in enumerate(["down", "up", "down", "up", "down"]):
        c = Completion(
            user_id=user.id, mission_id=mission.id, place_id=place.id,
            capture_lat=47.6605, capture_lng=-117.4198,
            verified=True, location_rating=rating,
        )
        db_session.add(c)
    await db_session.commit()

    await _apply_auto_retire(db_session, place_id=place.id)
    refreshed = (await db_session.execute(select(Place).where(Place.id == place.id))).scalar_one()
    assert refreshed.status == "flagged"
```

- [ ] **Step 7.2: Implement**

Write to `src/dispatchzero/services/mission_flow.py`:

```python
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from sqlalchemy import desc, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.config import get_settings
from dispatchzero.models import (
    Completion, Mission, MissionStatus, Place, PlaceCategory, PlaceStatus,
    User, UserPlaceHistory,
)
from dispatchzero.services.photo import save_thumbnail
from dispatchzero.services.progression import week_start_utc, xp_for_completion
from dispatchzero.services.verification import verify_capture


class CaptureFailedError(RuntimeError):
    """Raised when photo capture verification fails. Message contains the fail_reason."""


async def capture_mission(
    *,
    db: AsyncSession,
    user: User,
    mission: Mission,
    place: Place,
    raw_photo: bytes,
    capture_lat: float,
    capture_lng: float,
    capture_accuracy_m: float | None,
) -> Completion:
    settings = get_settings()

    # PostGIS geography column round-trips as EWKB; pull text representation for lat/lng
    target_lat, target_lng = await _place_lat_lng(db, place.id)

    result = verify_capture(
        raw_bytes=raw_photo,
        capture_lat=capture_lat, capture_lng=capture_lng,
        target_lat=target_lat, target_lng=target_lng,
        category=PlaceCategory(place.category),
        freshness_window_seconds=settings.exif_freshness_window_seconds,
    )
    if not result.verified:
        raise CaptureFailedError(result.fail_reason or "unknown")

    # Reserve a completion id so we can name the photo file before the row is committed
    completion_id = uuid.uuid4()
    photo_dir = Path(settings.photo_upload_dir) / "completions" / str(user.id)
    photo_path = photo_dir / f"{completion_id}.jpg"
    save_thumbnail(
        raw_photo, photo_path,
        max_dim=settings.photo_max_dimension, quality=settings.photo_jpeg_quality,
    )

    xp = xp_for_completion(PlaceCategory(place.category))

    completion = Completion(
        id=completion_id,
        user_id=user.id, mission_id=mission.id, place_id=place.id,
        photo_url=str(photo_path),
        capture_lat=capture_lat, capture_lng=capture_lng,
        capture_accuracy_m=capture_accuracy_m,
        had_exif=result.had_exif,
        exif_datetime_delta_seconds=result.exif_delta_seconds,
        had_exif_gps=result.had_exif_gps,
        verified=True,
        xp_awarded=xp,
    )
    db.add(completion)

    # Update user XP + weekly counter
    await _bump_user_progression(db, user=user, xp=xp)

    # Upsert user_place_history (latest completion bumps last_completed_at)
    await db.execute(
        pg_insert(UserPlaceHistory)
        .values(
            id=uuid.uuid4(), user_id=user.id, place_id=place.id,
            last_completed_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            index_elements=["user_id", "place_id"],
            set_={"last_completed_at": datetime.now(timezone.utc)},
        )
    )

    # Mission implicit-completion counter
    await db.execute(
        update(Mission)
        .where(Mission.id == mission.id)
        .values(implicit_completions=Mission.implicit_completions + 1)
    )

    await db.commit()
    await db.refresh(completion)
    return completion


async def rate_completion(
    *,
    db: AsyncSession,
    user: User,
    completion: Completion,
    location_rating: Literal["up", "down"] | None,
    mission_rating: Literal["up", "down"] | None,
    location_reason: str | None,
) -> Completion:
    """Apply a two-axis rating to a completion. Idempotent (overwrite if re-submitted)."""
    completion.location_rating = location_rating
    completion.mission_rating = mission_rating
    completion.location_reason = location_reason
    db.add(completion)

    # Aggregate counters on Place
    if location_rating == "up":
        await db.execute(
            update(Place).where(Place.id == completion.place_id)
            .values(location_thumbs_up=Place.location_thumbs_up + 1)
        )
    elif location_rating == "down":
        await db.execute(
            update(Place).where(Place.id == completion.place_id)
            .values(location_thumbs_down=Place.location_thumbs_down + 1)
        )

    # Aggregate counters on Mission + regen flag
    if mission_rating == "up":
        await db.execute(
            update(Mission).where(Mission.id == completion.mission_id)
            .values(mission_thumbs_up=Mission.mission_thumbs_up + 1)
        )
    elif mission_rating == "down":
        await db.execute(
            update(Mission).where(Mission.id == completion.mission_id)
            .values(
                mission_thumbs_down=Mission.mission_thumbs_down + 1,
                status=MissionStatus.NEEDS_REGEN.value,
            )
        )

    await db.commit()
    if location_rating == "down":
        await _apply_auto_retire(db, place_id=completion.place_id)
        await db.commit()
    await db.refresh(completion)
    return completion


# ---- internals ----

async def _place_lat_lng(db: AsyncSession, place_id: uuid.UUID) -> tuple[float, float]:
    """Read a Place's coordinates as (lat, lng) using PostGIS ST_X/ST_Y."""
    from sqlalchemy import text
    row = (await db.execute(
        text("SELECT ST_Y(coordinates::geometry), ST_X(coordinates::geometry) "
             "FROM places WHERE id = :pid"),
        {"pid": place_id},
    )).one()
    return float(row[0]), float(row[1])


async def _bump_user_progression(db: AsyncSession, *, user: User, xp: int) -> None:
    settings_now = datetime.now(timezone.utc)
    user_week_start = week_start_utc(settings_now)
    # If user.streak_last_date (we'll add later) was in a prior week, roll missions_last_week.
    # For v1 we simply increment missions_this_week; weekly rollover handled lazily on read.
    await db.execute(
        update(User).where(User.id == user.id).values(
            xp=User.xp + xp,
            missions_this_week=User.missions_this_week + 1,
            last_login_at=settings_now,
        )
    )


async def _apply_auto_retire(db: AsyncSession, *, place_id: uuid.UUID) -> None:
    """If 3+ of the last 5 location ratings on this place are 'down', flag it."""
    rows = (await db.execute(
        select(Completion.location_rating)
        .where(
            Completion.place_id == place_id,
            Completion.location_rating.in_(["up", "down"]),
        )
        .order_by(desc(Completion.completed_at))
        .limit(5)
    )).scalars().all()
    if len(rows) < 5:
        return
    if sum(1 for r in rows if r == "down") >= 3:
        await db.execute(
            update(Place).where(Place.id == place_id)
            .values(status=PlaceStatus.FLAGGED.value)
        )
```

- [ ] **Step 7.3: Run, fix any issues, commit**

```bash
./deploy/test.sh 2>&1 | tail -10
git add src/dispatchzero/services/mission_flow.py tests/test_mission_flow_service.py
git commit -m "feat: mission flow orchestrator (capture + rate + auto-retire)"
```

---

### Task 8: Schemas + HTTP routes for the four endpoints

**Files:**
- Create: `src/dispatchzero/schemas/completions.py`
- Modify: `src/dispatchzero/missions/routes.py`
- Create: `tests/test_missions_flow_routes.py`

- [ ] **Step 8.1: Write the schemas**

Write to `src/dispatchzero/schemas/completions.py`:

```python
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

LocationReason = Literal["gone", "not_found", "inaccessible", "unsafe"]


class MissionRequestIn(BaseModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]
    radius_m: Annotated[int, Field(ge=100, le=10_000)] = 2000
    adventure_style: Literal["pulp", "agency", "guild"] | None = None


class CompletionOut(BaseModel):
    id: uuid.UUID
    mission_id: uuid.UUID
    place_id: uuid.UUID
    verified: bool
    xp_awarded: int
    photo_url: str | None
    completed_at: str  # ISO


class DebriefOut(BaseModel):
    completion: CompletionOut
    user_xp: int
    user_missions_this_week: int


class RateIn(BaseModel):
    location_rating: Literal["up", "down"] | None = None
    mission_rating: Literal["up", "down"] | None = None
    location_reason: LocationReason | None = None
```

- [ ] **Step 8.2: Extend missions/routes.py**

Add these endpoints to `src/dispatchzero/missions/routes.py`:

```python
import uuid as _uuid
from typing import Annotated as _Annotated

import redis.asyncio as aioredis
from fastapi import File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from dispatchzero.models import Completion, Place
from dispatchzero.schemas.completions import (
    CompletionOut, DebriefOut, MissionRequestIn, RateIn,
)
from dispatchzero.schemas.missions import MissionOut
from dispatchzero.services.discovery import discover_nearby
from dispatchzero.services.mission_flow import (
    CaptureFailedError, capture_mission, rate_completion,
)
from dispatchzero.services.missions import (
    MissionGenerationError, get_or_generate_mission,
)
# (existing imports stay)


async def _get_redis_for_routes(
    settings: _Annotated["Settings", Depends(get_settings)],
) -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


@router.post("/request", response_model=MissionOut)
async def request_mission(
    payload: MissionRequestIn,
    user: _Annotated[User, Depends(current_user)],
    db: _Annotated[AsyncSession, Depends(get_session)],
    redis: _Annotated[aioredis.Redis, Depends(_get_redis_for_routes)],
) -> MissionOut:
    places = await discover_nearby(
        db=db, redis=redis, user=user,
        lat=payload.lat, lng=payload.lng, radius_m=payload.radius_m, limit=1,
    )
    if not places:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no eligible places nearby")
    place_id = places[0]["id"]
    try:
        mission = await get_or_generate_mission(
            db=db, user=user, place_id=place_id,
            adventure_style=payload.adventure_style,
        )
    except MissionGenerationError as e:
        msg = str(e).lower()
        if "not found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the dispatch line is unreliable, agent — try again",
        ) from e

    return MissionOut(
        id=mission.id, place_id=mission.place_id,
        adventure_style=mission.adventure_style,
        dispatch_summary=mission.dispatch_summary,
        briefing_text=mission.briefing_text,
        clue=mission.clue, badge_framing=mission.badge_framing,
        audio_url=mission.audio_url, ai_model=mission.ai_model,
        status=mission.status,
    )


@router.post("/{mission_id}/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_mission(
    mission_id: _uuid.UUID,
    user: _Annotated[User, Depends(current_user)],
    db: _Annotated[AsyncSession, Depends(get_session)],
) -> None:
    # v1: no DB write — accept is a client-side state transition only.
    # We still validate that the mission exists so the client gets a clean 404.
    from dispatchzero.models import Mission
    m = (await db.execute(select(Mission).where(Mission.id == mission_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")


@router.post("/{mission_id}/capture", response_model=DebriefOut)
async def capture(
    mission_id: _uuid.UUID,
    user: _Annotated[User, Depends(current_user)],
    db: _Annotated[AsyncSession, Depends(get_session)],
    photo: UploadFile = File(...),
    lat: float = Form(...),
    lng: float = Form(...),
    accuracy_m: float | None = Form(None),
) -> DebriefOut:
    from dispatchzero.models import Mission
    mission = (await db.execute(
        select(Mission).where(Mission.id == mission_id)
    )).scalar_one_or_none()
    if mission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    place = (await db.execute(
        select(Place).where(Place.id == mission.place_id)
    )).scalar_one()

    raw = await photo.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty photo upload")

    try:
        completion = await capture_mission(
            db=db, user=user, mission=mission, place=place,
            raw_photo=raw,
            capture_lat=lat, capture_lng=lng, capture_accuracy_m=accuracy_m,
        )
    except CaptureFailedError as e:
        # In-character: don't leak whether GPS or EXIF failed
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "the proof is not yet sufficient, agent — try again",
        ) from e

    # Re-fetch the user to get updated XP/weekly counter
    refreshed_user = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
    return DebriefOut(
        completion=CompletionOut(
            id=completion.id,
            mission_id=completion.mission_id,
            place_id=completion.place_id,
            verified=completion.verified,
            xp_awarded=completion.xp_awarded,
            photo_url=completion.photo_url,
            completed_at=completion.completed_at.isoformat(),
        ),
        user_xp=refreshed_user.xp,
        user_missions_this_week=refreshed_user.missions_this_week,
    )


@router.post("/completions/{completion_id}/rate", response_model=CompletionOut)
async def rate(
    completion_id: _uuid.UUID,
    payload: RateIn,
    user: _Annotated[User, Depends(current_user)],
    db: _Annotated[AsyncSession, Depends(get_session)],
) -> CompletionOut:
    completion = (await db.execute(
        select(Completion).where(Completion.id == completion_id)
    )).scalar_one_or_none()
    if completion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "completion not found")
    if completion.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your completion")

    await rate_completion(
        db=db, user=user, completion=completion,
        location_rating=payload.location_rating,
        mission_rating=payload.mission_rating,
        location_reason=payload.location_reason,
    )
    return CompletionOut(
        id=completion.id, mission_id=completion.mission_id, place_id=completion.place_id,
        verified=completion.verified, xp_awarded=completion.xp_awarded,
        photo_url=completion.photo_url,
        completed_at=completion.completed_at.isoformat(),
    )
```

(Note: The `from ... import ...` lines should be deduplicated against the existing top-of-file imports rather than added inside route bodies. Edit accordingly.)

- [ ] **Step 8.3: Write integration tests**

Write to `tests/test_missions_flow_routes.py`:

```python
import io
import json
from datetime import datetime

import httpx
import pytest
import respx

from dispatchzero.models import Place
from dispatchzero.services.photo import make_test_jpeg

SIGNUP = {"callsign": "Hunter", "password": "long-enough-password", "adventure_style": "agency"}


def _ollama_payload() -> dict:
    return {
        "id": "x", "model": "gpt-oss:120b",
        "choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps({
                "dispatch_summary": "Dispatch.", "briefing_text": "Briefing body.",
                "clue": "Hint.", "badge_framing": "Badge",
            })},
        }],
    }


def _overpass_one() -> dict:
    return {"elements": [{
        "type": "node", "id": 9001, "lat": 47.6605, "lon": -117.4198,
        "tags": {"name": "Test Mural", "tourism": "artwork", "artwork_type": "mural"},
    }]}


@pytest.mark.asyncio
async def test_full_flow_request_capture_rate(
    client, db_session, redis_client, tmp_path, monkeypatch,
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_MODEL", "gpt-oss:120b")
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))

    await client.post("/auth/signup", json=SIGNUP)

    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json=_overpass_one())
        )
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )

        # 1) request
        r1 = await client.post("/missions/request", json={
            "lat": 47.6605, "lng": -117.4198, "radius_m": 2000,
        })
        assert r1.status_code == 200, r1.text
        mission = r1.json()
        mission_id = mission["id"]

        # 2) accept
        r2 = await client.post(f"/missions/{mission_id}/accept")
        assert r2.status_code == 204

        # 3) capture
        photo_bytes = make_test_jpeg(captured_at=datetime.utcnow())
        r3 = await client.post(
            f"/missions/{mission_id}/capture",
            files={"photo": ("p.jpg", photo_bytes, "image/jpeg")},
            data={"lat": "47.6605", "lng": "-117.4198", "accuracy_m": "8.0"},
        )
        assert r3.status_code == 200, r3.text
        debrief = r3.json()
        assert debrief["completion"]["verified"] is True
        assert debrief["completion"]["xp_awarded"] == 15  # mural
        assert debrief["user_xp"] == 15
        assert debrief["user_missions_this_week"] == 1
        completion_id = debrief["completion"]["id"]

        # 4) rate
        r4 = await client.post(
            f"/missions/completions/{completion_id}/rate",
            json={"location_rating": "up", "mission_rating": "up"},
        )
        assert r4.status_code == 200


@pytest.mark.asyncio
async def test_capture_returns_422_for_out_of_radius(
    client, db_session, redis_client, tmp_path, monkeypatch,
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    await client.post("/auth/signup", json=SIGNUP)

    # Seed a place + mission directly
    place = Place(
        osm_type="node", osm_id=1, name="X", category="sculpture",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)", tags={},
    )
    db_session.add(place); await db_session.commit(); await db_session.refresh(place)
    from dispatchzero.models import Mission
    mission = Mission(
        place_id=place.id, adventure_style="agency",
        dispatch_summary="x", briefing_text="y",
    )
    db_session.add(mission); await db_session.commit(); await db_session.refresh(mission)

    photo_bytes = make_test_jpeg(captured_at=datetime.utcnow())
    r = await client.post(
        f"/missions/{mission.id}/capture",
        files={"photo": ("p.jpg", photo_bytes, "image/jpeg")},
        data={"lat": "47.6900", "lng": "-117.4000", "accuracy_m": "8.0"},  # ~3km away
    )
    assert r.status_code == 422
    assert "proof" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_capture_requires_auth(client, db_session, redis_client):
    client.cookies.clear()
    photo_bytes = make_test_jpeg(captured_at=datetime.utcnow())
    r = await client.post(
        "/missions/00000000-0000-0000-0000-000000000000/capture",
        files={"photo": ("p.jpg", photo_bytes, "image/jpeg")},
        data={"lat": "0", "lng": "0"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_rate_rejects_someone_elses_completion(
    client, db_session, redis_client, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PHOTO_UPLOAD_DIR", str(tmp_path))
    # Create user A's completion
    await client.post("/auth/signup", json={**SIGNUP, "callsign": "AgentA"})
    place = Place(
        osm_type="node", osm_id=2, name="Y", category="sculpture",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)", tags={},
    )
    db_session.add(place); await db_session.commit()
    from dispatchzero.models import Mission, Completion, User
    from sqlalchemy import select
    user_a = (await db_session.execute(select(User).where(User.callsign_lower == "agenta"))).scalar_one()
    mission = Mission(place_id=place.id, adventure_style="agency",
                      dispatch_summary="x", briefing_text="y")
    db_session.add(mission); await db_session.commit(); await db_session.refresh(mission)
    completion = Completion(
        user_id=user_a.id, mission_id=mission.id, place_id=place.id,
        capture_lat=47.6605, capture_lng=-117.4198, verified=True,
    )
    db_session.add(completion); await db_session.commit(); await db_session.refresh(completion)

    # Sign in as user B and try to rate user A's completion
    client.cookies.clear()
    await client.post("/auth/signup", json={**SIGNUP, "callsign": "AgentB"})
    r = await client.post(
        f"/missions/completions/{completion.id}/rate",
        json={"location_rating": "down"},
    )
    assert r.status_code == 403
```

- [ ] **Step 8.4: Run + commit**

```bash
./deploy/test.sh 2>&1 | tail -10
git add src/dispatchzero/schemas/completions.py src/dispatchzero/missions/routes.py tests/test_missions_flow_routes.py
git commit -m "feat: mission flow routes (request, accept, capture multipart, rate) with full integration tests"
```

---

### Task 9: Volume mount for /uploads in production

**Files:**
- Modify: `docker-compose.prod.yml`

- [ ] **Step 9.1: Add the bind mount**

In `docker-compose.prod.yml`, add to the `app:` section:

```yaml
  app:
    restart: unless-stopped
    ports: !reset []
    environment:
      APP_ENV: production
    volumes:
      - /opt/dispatchzero/uploads:/uploads
```

- [ ] **Step 9.2: Create the directory on VPS**

```bash
ssh root@89.167.39.152 "mkdir -p /opt/dispatchzero/uploads/completions && chmod 755 /opt/dispatchzero/uploads"
```

- [ ] **Step 9.3: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "feat: bind-mount /opt/dispatchzero/uploads into app container"
```

---

### Task 10: Deploy + smoke verify (full lifecycle against real Ollama + real OSM data)

- [ ] **Step 10.1: Deploy**

```bash
./deploy/deploy.sh
```

Expected: alembic upgrades to `0005`. Healthcheck OK.

- [ ] **Step 10.2: Verify migration applied**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app alembic current"
```

Expected: `0005 (head)`.

- [ ] **Step 10.3: Build a test JPEG locally and run the full flow against prod**

```bash
# Generate a fresh test JPEG with EXIF DateTimeOriginal = now
python3 -c "
import io, sys
from datetime import datetime
import piexif
from PIL import Image

img = Image.new('RGB', (1200, 1200), color=(80, 90, 100))
exif = {'0th':{}, 'Exif':{piexif.ExifIFD.DateTimeOriginal: datetime.utcnow().strftime('%Y:%m:%d %H:%M:%S').encode()}, 'GPS':{}, '1st':{}, 'thumbnail': None}
img.save('/tmp/test_capture.jpg', format='JPEG', exif=piexif.dump(exif))
print('wrote /tmp/test_capture.jpg')
"

COOKIES=$(mktemp)
curl -sS -c "$COOKIES" -X POST https://dispatchzero.ataary.com/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"callsign":"smoketest_p5","password":"smoketest-very-long-password","adventure_style":"agency"}' > /dev/null

echo "===== /missions/request (Spokane Garbage Goat area) ====="
MISSION_ID=$(curl -sS -b "$COOKIES" -X POST https://dispatchzero.ataary.com/missions/request \
  -H "Content-Type: application/json" \
  -d '{"lat": 47.6605131, "lng": -117.4197590, "radius_m": 2000}' \
  | tee /tmp/req.json | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "mission_id: $MISSION_ID"
PLACE_ID=$(python3 -c "import json; print(json.load(open('/tmp/req.json'))['place_id'])")
echo "place_id: $PLACE_ID"

echo "===== look up the actual coordinates of that place ====="
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -tAc \"SELECT ST_Y(coordinates::geometry), ST_X(coordinates::geometry) FROM places WHERE id = '$PLACE_ID';\""
# Note the lat,lng — pass them as the capture lat/lng below

echo
echo "===== /missions/{id}/accept ====="
curl -sS -b "$COOKIES" -X POST -o /dev/null -w "%{http_code}\n" \
  https://dispatchzero.ataary.com/missions/$MISSION_ID/accept

echo
echo "===== /missions/{id}/capture (multipart, with EXIF-fresh JPEG at the place's coords) ====="
# Use the lat/lng from the previous query
TARGET_LAT=$(ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -tAc \"SELECT ST_Y(coordinates::geometry) FROM places WHERE id = '$PLACE_ID';\"")
TARGET_LNG=$(ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -tAc \"SELECT ST_X(coordinates::geometry) FROM places WHERE id = '$PLACE_ID';\"")
echo "shooting at $TARGET_LAT, $TARGET_LNG"
curl -sS -b "$COOKIES" -X POST https://dispatchzero.ataary.com/missions/$MISSION_ID/capture \
  -F "photo=@/tmp/test_capture.jpg;type=image/jpeg" \
  -F "lat=$TARGET_LAT" -F "lng=$TARGET_LNG" -F "accuracy_m=8.0" \
  | tee /tmp/cap.json | python3 -m json.tool

COMPLETION_ID=$(python3 -c "import json; print(json.load(open('/tmp/cap.json'))['completion']['id'])")
echo
echo "===== /missions/completions/{id}/rate ====="
curl -sS -b "$COOKIES" -X POST https://dispatchzero.ataary.com/missions/completions/$COMPLETION_ID/rate \
  -H "Content-Type: application/json" \
  -d '{"location_rating": "up", "mission_rating": "up"}' \
  | python3 -m json.tool

echo
echo "===== verify XP and weekly count on the user ====="
curl -sS -b "$COOKIES" https://dispatchzero.ataary.com/auth/me | python3 -m json.tool

rm -f "$COOKIES" /tmp/test_capture.jpg /tmp/req.json /tmp/cap.json
```

Expected:
- `request` returns a generated mission for a Spokane place
- `accept` returns 204
- `capture` returns 200, debrief contains `verified: true` and `xp_awarded > 0`
- `rate` returns the completion with the ratings recorded
- `/auth/me` shows updated `xp` and `missions_this_week`

- [ ] **Step 10.4: Verify the photo file landed on disk**

```bash
ssh root@89.167.39.152 "ls -la /opt/dispatchzero/uploads/completions/*/ | head -5"
```

Expected: a JPEG file < 50KB exists at the expected path.

- [ ] **Step 10.5: Verify EXIF was stripped from the stored thumbnail**

```bash
ssh root@89.167.39.152 "find /opt/dispatchzero/uploads -name '*.jpg' -newer /tmp -print -quit | xargs -I {} cp {} /tmp/check.jpg"
ssh root@89.167.39.152 "python3 -c 'import piexif; print(piexif.load(\"/tmp/check.jpg\")[\"Exif\"])'"
```

Expected: empty `{}` (EXIF stripped).

- [ ] **Step 10.6: Cleanup smoketest user (and their completion + photo file)**

```bash
ssh root@89.167.39.152 "
USER_ID=\$(cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -tAc \"SELECT id FROM users WHERE callsign_lower = 'smoketest_p5'\")
echo \"deleting completions for user \$USER_ID\"
cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -c \"DELETE FROM user_place_history WHERE user_id = '\$USER_ID'; DELETE FROM completions WHERE user_id = '\$USER_ID'; DELETE FROM users WHERE id = '\$USER_ID';\"
rm -rf /opt/dispatchzero/uploads/completions/\$USER_ID
"
```

- [ ] **Step 10.7: Final health check**

```bash
ssh root@89.167.39.152 "systemctl is-active paperclip.service && free -h | head -2 && df -h /"
```

Expected: `active`, RAM available > 1.5 GB, disk used < 88%.

---

## Phase 5 — Definition of Done

- All tests pass via `./deploy/test.sh`.
- Production smoke flow (signup → /missions/request → /accept → /capture with synthetic JPEG → /rate) returns 200 at every step.
- Completion row written; XP and `missions_this_week` advance on the User row.
- Photo file written to `/opt/dispatchzero/uploads/completions/{user_id}/{completion_id}.jpg` with stripped EXIF.
- Out-of-radius capture returns 422 with the in-character message.
- Stale EXIF capture returns 422 with the in-character message.
- Migration `0005` applied; `completions` table exists with the audit fields.
- Mission prompt no longer leaks "0.00000, 0.00000" coordinates.
- Paperclip restart count unchanged.

---

## Critical Files To Be Created In Phase 5

| File | Purpose |
|---|---|
| `src/dispatchzero/services/photo.py` | Haversine + EXIF read + thumbnail save (pure helpers) |
| `src/dispatchzero/services/verification.py` | Combined GPS + freshness gate |
| `src/dispatchzero/services/progression.py` | XP table + week-start helper |
| `src/dispatchzero/services/mission_flow.py` | capture + rate orchestrator |
| `src/dispatchzero/schemas/completions.py` | Pydantic for /request, /capture, /rate |
| `src/dispatchzero/models/completion.py` | Completion ORM |
| `src/dispatchzero/missions/routes.py` (extended) | Four new endpoints |
| `alembic/versions/0005_completions.py` | Migration |

---

## Open Decisions (override before starting)

| Decision | Default | Where to change |
|---|---|---|
| GPS radius per category | mural 60, sculpture 40, memorial 50, historic 80, viewpoint 100 (m) | `RADIUS_M_BY_CATEGORY` in `services/verification.py` |
| EXIF freshness window | 600 s (10 min) | `Settings.exif_freshness_window_seconds` |
| XP table | base 10 + (mural 5, sculpture 3, memorial 3, historic 2, viewpoint 1) | `services/progression.py` |
| `/missions/{id}/accept` behavior | No-op success | Add a `MissionAttempt` table later if accept-rate analytics matter |
| Mission regen on single thumbs-down | Yes (set status=needs_regen immediately) | Could require N≥2 down to suppress noise — adjust in `rate_completion` |
| Photo dimension cap | 600 × 600 | `Settings.photo_max_dimension` |
| Photo JPEG quality | 70 | `Settings.photo_jpeg_quality` |
| Auto-retire trigger | 3 of last 5 location_ratings = down | `_apply_auto_retire` in `services/mission_flow.py` |
| Photo serving endpoint | NOT in this phase (added in Phase 9 mission cards) | Defer |
| Public completion page | Phase 10 (social sharing) | Defer |

---

## What Comes Next After Phase 5

**This is the launchable backend.** After Phase 5, the API can drive a complete mission lifecycle. Phase 6 (frontend foundation) and Phase 7 (mission UI screens) build the PWA on top of these endpoints. The Phase 6 plan will also pick up the three Zero avatar PNGs at the project root.

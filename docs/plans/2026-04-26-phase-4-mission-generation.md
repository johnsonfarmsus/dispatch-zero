# Phase 4: Mission Generation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given a `place_id` and an adventure style, the system returns a mission briefing — either from the library (if a previously-validated mission for this place+style exists) or freshly written via Ollama Cloud. The endpoint `POST /missions/generate` becomes the bridge between Phase 3's discovered places and Phase 5's mission flow.

**Architecture:** Three layers, plus the persistence model.

1. **Ollama client** (`integrations/ollama.py`) — async HTTP wrapper around Ollama Cloud's OpenAI-compatible chat-completions endpoint, with one retry on transient failure, JSON-mode response, and Pydantic validation of the structured output.
2. **Prompt builder** (`services/mission_prompts.py`) — pure function, three style-specific templates (Pulp / Agency / Guild). All produce JSON with the same shape; only voice and tone differ. Always signs as "Zero" with style-appropriate phrasing per the locked decision.
3. **Mission service** (`services/missions.py`) — orchestrator: library lookup → on miss, build prompt → call Ollama → validate → persist → return. Library reuse logic and the no-Ollama-call hot path live here.
4. **Persistence** (`models/mission.py`, `models/mission_stop.py`) — matches the spec's Mission and MissionStop schemas. v1 only writes single-stop missions but the model supports multi-stop from day one.

**Tech additions:** None. `httpx` is already in main deps from Phase 3, `respx` is already in dev deps. Ollama Cloud uses HTTPS + bearer auth — nothing exotic.

**External-service rules (Ollama Cloud):**

| Concern | Approach |
|---|---|
| Auth | `Authorization: Bearer ${OLLAMA_API_KEY}` header on every request. Read from env. |
| Endpoint | OpenAI-compatible `https://ollama.com/v1/chat/completions`. Plain JSON in/out. |
| Model | Configurable via `OLLAMA_MODEL` env. Default proposal: `gpt-oss:120b`. Override per Trevor's actual Ollama Cloud entitlements. |
| Structured output | Pass `response_format: {"type": "json_object"}`. Validate the returned JSON with Pydantic. |
| Retries | One retry on 5xx or transport error. Zero retries on 4xx. Total wall-time budget: 15s. |
| Failure mode | If Ollama returns garbage twice or 5xx persists: 503 to the client with an in-character message. We do NOT fall back to a canned mission — the product feel demands either a real briefing or an honest "dispatch unavailable, agent." |
| Prompt caching | None (missions should feel fresh). Library reuse is the dedup mechanism, not prompt caching. |

**Decision defaults (override before starting):**

| Decision | Default | Why |
|---|---|---|
| Sync vs. async generation | **Sync** with 15s timeout, 5s p50 target | Simpler than background jobs; UI shows "issuing dispatch…" spinner during the request. Async is a Phase 12+ optimization if Ollama latency proves painful. |
| Model | `gpt-oss:120b` (env-overridable via `OLLAMA_MODEL`) | Solid general-purpose reasoning + creative writing. Trevor confirms his Ollama Cloud account has access. |
| Per-user rate limit | None in v1 (rely on natural rate-limit: walk to a place to "consume" a generation) | Add later if abuse surfaces. Trevor's on a flat Ollama plan so cost isn't immediate. |
| Library reuse query | `SELECT * FROM missions WHERE place_id = ? AND adventure_style = ? AND status = 'active' AND mission_thumbs_down < 3 ORDER BY mission_thumbs_up DESC, created_at ASC LIMIT 1` | Per spec; "best loved" mission wins; ties broken by oldest. |
| Mission length | dispatch_summary ≤ 280 chars (3 lines), briefing_text ≤ 2000 chars, clue ≤ 200 chars, badge_framing ≤ 80 chars | Validated server-side; if Ollama exceeds, retry once, then 503. |
| Sign-off enforcement | Soft — handled in the prompt, not post-validated | Asking the model nicely is enough; we're not building a profanity filter. |
| Idempotency | POSTing twice for the same place returns the cached library entry the second time (this *is* the library hit) | Matches spec; no separate idempotency layer needed. |

**Repo layout deltas after this phase:**

```
dispatch-zero/
├── src/dispatchzero/
│   ├── (existing)
│   ├── integrations/
│   │   ├── (existing: nominatim, overpass, wikidata, _throttle, _cache)
│   │   └── ollama.py                  # NEW
│   ├── models/
│   │   ├── (existing)
│   │   ├── mission.py                 # NEW
│   │   └── mission_stop.py            # NEW
│   ├── services/
│   │   ├── (existing: scoring, discovery)
│   │   ├── missions.py                # NEW
│   │   └── mission_prompts.py         # NEW
│   ├── schemas/
│   │   ├── (existing)
│   │   └── missions.py                # NEW (MissionContent, MissionGenerateIn, MissionOut)
│   └── missions/                      # NEW
│       ├── __init__.py
│       └── routes.py                  # NEW (POST /missions/generate)
├── alembic/versions/
│   └── 0004_missions.py               # NEW
└── tests/
    ├── (existing)
    ├── test_integrations_ollama.py    # NEW
    ├── test_mission_prompts.py        # NEW
    ├── test_missions_service.py       # NEW (library hit + miss + retry)
    └── test_missions_routes.py        # NEW (HTTP integration)
```

---

### Task 1: Settings additions for Ollama

**Files:**
- Modify: `src/dispatchzero/config.py`
- Create: `tests/test_config_ollama.py`

- [ ] **Step 1.1: Write failing test**

Write to `tests/test_config_ollama.py`:

```python
from dispatchzero.config import Settings


def test_ollama_settings_have_sensible_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    s = Settings()
    assert s.ollama_api_key == "test-key"
    assert s.ollama_base_url == "https://ollama.com/v1"
    assert s.ollama_model == "gpt-oss:120b"
    assert s.ollama_timeout_seconds == 15
```

- [ ] **Step 1.2: Run, confirm fail**

```bash
./deploy/test.sh 2>&1 | grep -E "test_config_ollama|FAILED|PASSED" | tail -5
```

Expected: AttributeError on `ollama_api_key`.

- [ ] **Step 1.3: Implement**

In `src/dispatchzero/config.py`, append fields to the `Settings` class (after the rate-limit fields):

```python
    # Ollama Cloud
    ollama_api_key: str = ""
    ollama_base_url: str = "https://ollama.com/v1"
    ollama_model: str = "gpt-oss:120b"
    ollama_timeout_seconds: int = 15
```

Note: `ollama_api_key` defaults to empty string so tests that don't need Ollama don't have to set it. Code that calls Ollama must check for emptiness and raise a clear error.

- [ ] **Step 1.4: Add the env var to prod `.env` on VPS 2 (deferred until Step 8 — needs the real key)**

For now, just note: before Task 8 (deploy), Trevor must add `OLLAMA_API_KEY=...` to `/opt/dispatchzero/.env` on VPS 2.

- [ ] **Step 1.5: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | tail -5
```

- [ ] **Step 1.6: Commit**

```bash
git add src/dispatchzero/config.py tests/test_config_ollama.py
git commit -m "feat: add Ollama settings (api_key, base_url, model, timeout)"
```

---

### Task 2: Mission + MissionStop models + migration 0004

**Files:**
- Create: `src/dispatchzero/models/mission.py`
- Create: `src/dispatchzero/models/mission_stop.py`
- Modify: `src/dispatchzero/models/__init__.py`
- Create: `alembic/versions/0004_missions.py`

- [ ] **Step 2.1: Create the Mission model**

Write to `src/dispatchzero/models/mission.py`:

```python
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class MissionStatus(StrEnum):
    ACTIVE = "active"
    NEEDS_REGEN = "needs_regen"
    RETIRED = "retired"


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("places.id", ondelete="CASCADE"),
        nullable=False,
    )
    adventure_style: Mapped[str] = mapped_column(String(16), nullable=False)
    dispatch_summary: Mapped[str] = mapped_column(String(400), nullable=False)
    briefing_text: Mapped[str] = mapped_column(String(2200), nullable=False)
    clue: Mapped[str | None] = mapped_column(String(240), nullable=True)
    badge_framing: Mapped[str | None] = mapped_column(String(120), nullable=True)

    mission_thumbs_up: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    mission_thumbs_down: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    implicit_completions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    audio_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
        Index("ix_missions_place_style_status", "place_id", "adventure_style", "status"),
    )
```

- [ ] **Step 2.2: Create the MissionStop model**

Write to `src/dispatchzero/models/mission_stop.py`:

```python
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dispatchzero.models.base import Base


class MissionStop(Base):
    __tablename__ = "mission_stops"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        UniqueConstraint("mission_id", "place_id", name="uq_mission_stop"),
    )
```

- [ ] **Step 2.3: Register models**

Replace `src/dispatchzero/models/__init__.py`:

```python
from dispatchzero.models.base import Base
from dispatchzero.models.mission import Mission, MissionStatus
from dispatchzero.models.mission_stop import MissionStop
from dispatchzero.models.place import Place, PlaceCategory, PlaceStatus
from dispatchzero.models.user import AdventureStyle, User
from dispatchzero.models.user_place_history import UserPlaceHistory

__all__ = [
    "AdventureStyle",
    "Base",
    "Mission",
    "MissionStatus",
    "MissionStop",
    "Place",
    "PlaceCategory",
    "PlaceStatus",
    "User",
    "UserPlaceHistory",
]
```

- [ ] **Step 2.4: Write migration 0004 — one statement per `op.execute()`**

> **Critical:** asyncpg rejects multi-statement prepared statements (this bit Phase 3). Each `CREATE TABLE` and `CREATE INDEX` must be its own `op.execute()` call.

Write to `alembic/versions/0004_missions.py`:

```python
"""add missions and mission_stops tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE missions (
            id UUID PRIMARY KEY,
            place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
            adventure_style VARCHAR(16) NOT NULL,
            dispatch_summary VARCHAR(400) NOT NULL,
            briefing_text VARCHAR(2200) NOT NULL,
            clue VARCHAR(240),
            badge_framing VARCHAR(120),
            mission_thumbs_up INTEGER NOT NULL DEFAULT 0,
            mission_thumbs_down INTEGER NOT NULL DEFAULT 0,
            implicit_completions INTEGER NOT NULL DEFAULT 0,
            audio_url VARCHAR(400),
            ai_model VARCHAR(64),
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX ix_missions_place_style_status "
        "ON missions (place_id, adventure_style, status)"
    )
    op.execute("""
        CREATE TABLE mission_stops (
            id UUID PRIMARY KEY,
            mission_id UUID NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
            place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
            display_order INTEGER NOT NULL DEFAULT 0,
            required BOOLEAN NOT NULL DEFAULT TRUE,
            CONSTRAINT uq_mission_stop UNIQUE (mission_id, place_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mission_stops")
    op.execute("DROP TABLE IF EXISTS missions")
```

- [ ] **Step 2.5: Run tests to confirm models load**

```bash
./deploy/test.sh 2>&1 | tail -5
```

Expected: all existing tests still pass.

- [ ] **Step 2.6: Commit**

```bash
git add src/dispatchzero/models alembic/versions/0004_missions.py
git commit -m "feat: add Mission and MissionStop models with migration 0004"
```

---

### Task 3: Mission content schemas

**Files:**
- Create: `src/dispatchzero/schemas/missions.py`
- Create: `tests/test_schemas_missions.py`

- [ ] **Step 3.1: Write failing tests**

Write to `tests/test_schemas_missions.py`:

```python
import uuid

import pytest
from pydantic import ValidationError

from dispatchzero.schemas.missions import MissionContent, MissionGenerateIn, MissionOut


def test_mission_content_accepts_valid():
    c = MissionContent(
        dispatch_summary="Two short lines.",
        briefing_text="A full paragraph of the briefing text.",
        clue="Look for the brass plaque.",
        badge_framing="First Documented Sculpture",
    )
    assert c.dispatch_summary == "Two short lines."


def test_mission_content_rejects_overlong_dispatch_summary():
    with pytest.raises(ValidationError):
        MissionContent(
            dispatch_summary="x" * 500,
            briefing_text="ok",
            clue=None,
            badge_framing=None,
        )


def test_mission_content_rejects_empty_briefing():
    with pytest.raises(ValidationError):
        MissionContent(
            dispatch_summary="ok",
            briefing_text="",
            clue=None,
            badge_framing=None,
        )


def test_mission_generate_in_requires_place_id():
    with pytest.raises(ValidationError):
        MissionGenerateIn()


def test_mission_generate_in_accepts_optional_style():
    g = MissionGenerateIn(place_id=uuid.uuid4(), adventure_style="agency")
    assert g.adventure_style == "agency"


def test_mission_generate_in_rejects_unknown_style():
    with pytest.raises(ValidationError):
        MissionGenerateIn(place_id=uuid.uuid4(), adventure_style="ranger")
```

- [ ] **Step 3.2: Run, confirm fail**

```bash
./deploy/test.sh 2>&1 | grep -E "test_schemas_missions|FAILED|PASSED" | tail -5
```

Expected: ImportError.

- [ ] **Step 3.3: Implement**

Write to `src/dispatchzero/schemas/missions.py`:

```python
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

AdventureStyle = Literal["pulp", "agency", "guild"]


class MissionContent(BaseModel):
    """The structured payload Ollama returns. Fields match the prompt contract."""

    dispatch_summary: Annotated[str, Field(min_length=1, max_length=400)]
    briefing_text: Annotated[str, Field(min_length=1, max_length=2200)]
    clue: Annotated[str | None, Field(max_length=240)] = None
    badge_framing: Annotated[str | None, Field(max_length=120)] = None


class MissionGenerateIn(BaseModel):
    place_id: uuid.UUID
    adventure_style: AdventureStyle | None = None  # defaults to user's profile


class MissionOut(BaseModel):
    id: uuid.UUID
    place_id: uuid.UUID
    adventure_style: str
    dispatch_summary: str
    briefing_text: str
    clue: str | None
    badge_framing: str | None
    audio_url: str | None
    ai_model: str | None
    status: str
```

- [ ] **Step 3.4: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | grep -E "test_schemas_missions|PASSED|FAILED" | tail -8
```

Expected: 6 passed.

- [ ] **Step 3.5: Commit**

```bash
git add src/dispatchzero/schemas/missions.py tests/test_schemas_missions.py
git commit -m "feat: pydantic schemas for mission content and generate request"
```

---

### Task 4: Style prompt builder (TDD, pure)

**Files:**
- Create: `src/dispatchzero/services/mission_prompts.py`
- Create: `tests/test_mission_prompts.py`

- [ ] **Step 4.1: Write failing tests**

Write to `tests/test_mission_prompts.py`:

```python
import pytest

from dispatchzero.services.mission_prompts import build_mission_prompt


def _ctx():
    return dict(
        callsign="Trevor_01",
        place_name="Garbage Goat",
        place_category="sculpture",
        place_description=None,
        place_lat=47.6605,
        place_lng=-117.4198,
    )


def test_pulp_prompt_mentions_pulp_style_cues_and_callsign():
    msgs = build_mission_prompt(style="pulp", **_ctx())
    text = "\n".join(m["content"] for m in msgs)
    assert "Trevor_01" in text
    assert "Garbage Goat" in text
    # Pulp tone cues
    assert any(w in text.lower() for w in ("expedition", "field", "dispatch"))
    # Always signed Zero, never persona names
    assert "Vale" not in text
    assert "Ashford" not in text
    assert "Warden" not in text


def test_agency_prompt_uses_clinical_register():
    msgs = build_mission_prompt(style="agency", **_ctx())
    text = "\n".join(m["content"] for m in msgs)
    assert "Trevor_01" in text
    assert any(w in text.lower() for w in ("classified", "operative", "asset", "directive"))
    assert "Vale" not in text


def test_guild_prompt_uses_ceremonial_register():
    msgs = build_mission_prompt(style="guild", **_ctx())
    text = "\n".join(m["content"] for m in msgs)
    assert "Trevor_01" in text
    assert any(w in text.lower() for w in ("guild", "ancient", "rite", "warden", "ceremony"))


def test_prompt_demands_json_response_format():
    msgs = build_mission_prompt(style="pulp", **_ctx())
    text = "\n".join(m["content"] for m in msgs)
    # The system message must instruct JSON shape
    assert "dispatch_summary" in text
    assert "briefing_text" in text
    assert "clue" in text
    assert "badge_framing" in text


def test_prompt_includes_description_when_present():
    msgs = build_mission_prompt(
        style="agency",
        callsign="X",
        place_name="Some Mural",
        place_category="mural",
        place_description="A 1974 fresco depicting the Spokane River.",
        place_lat=47.6,
        place_lng=-117.4,
    )
    text = "\n".join(m["content"] for m in msgs)
    assert "1974 fresco" in text


def test_unknown_style_raises():
    with pytest.raises(ValueError):
        build_mission_prompt(
            style="ranger",
            callsign="X",
            place_name="X",
            place_category="mural",
            place_description=None,
            place_lat=0,
            place_lng=0,
        )
```

- [ ] **Step 4.2: Run, confirm fail**

```bash
./deploy/test.sh 2>&1 | grep -E "test_mission_prompts|FAILED|PASSED" | tail -8
```

Expected: ImportError.

- [ ] **Step 4.3: Implement**

Write to `src/dispatchzero/services/mission_prompts.py`:

```python
"""Style-specific mission prompt builder.

Each style produces messages in OpenAI-compatible format (system + user).
All styles MUST instruct the model to sign as 'Zero' and to respond as a
JSON object with the four content fields.
"""
from typing import Literal

AdventureStyle = Literal["pulp", "agency", "guild"]

# Shared instruction appended to every system message — defines the JSON contract.
_JSON_CONTRACT = """
You MUST respond with a single JSON object containing exactly these fields:
{
  "dispatch_summary": "<2-3 short lines, max 280 characters, the spoken-out preview>",
  "briefing_text": "<full mission text, 100-1800 characters, paragraph-formatted>",
  "clue": "<one short directional or atmospheric hint, max 200 characters>",
  "badge_framing": "<short evocative name for any badge earned, max 80 characters>"
}

The handler ALWAYS signs as 'Zero' — never use any other name (no Vale, Ashford,
Warden, or other personas). The signature itself is identical across all styles;
only the surrounding phrasing varies.
"""

_PULP_SYSTEM = (
    "You are Zero, a handler dispatching field operatives on photography expeditions "
    "for The Archive — a pulp-adventure organization that recovers cultural artifacts "
    "and documents disappearing places. Your tone is warm, fast-thinking, lightly "
    "enthusiastic. You use words like 'expedition', 'field', 'dispatch', 'recover', "
    "'document'. You sign briefings like '— Zero. Do be careful.' or similar warm "
    "closings."
    + _JSON_CONTRACT
)

_AGENCY_SYSTEM = (
    "You are Zero, a controller dispatching assets on classified directives for The "
    "Agency — a covert organization whose purpose is never fully explained. Your tone "
    "is cold, clipped, professional, vaguely threatening. You use words like "
    "'classified', 'operative', 'asset', 'directive', 'objective', 'extraction'. "
    "Briefings read like declassified documents. You sign briefings simply '— Zero'."
    + _JSON_CONTRACT
)

_GUILD_SYSTEM = (
    "You are Zero, the voice of the ancient Guild — a ceremonial order that has been "
    "tracking sacred and historical sites since long before living memory. Your tone "
    "is slow, resonant, formal, faintly unsettling. You use words like 'guild', "
    "'rite', 'ancient', 'warden', 'ceremony', 'oath', 'mark'. You sign briefings like "
    "'— Zero. The matter is noted.' or similar formal closings."
    + _JSON_CONTRACT
)

_SYSTEM_BY_STYLE: dict[str, str] = {
    "pulp": _PULP_SYSTEM,
    "agency": _AGENCY_SYSTEM,
    "guild": _GUILD_SYSTEM,
}


def build_mission_prompt(
    *,
    style: AdventureStyle,
    callsign: str,
    place_name: str,
    place_category: str,
    place_description: str | None,
    place_lat: float,
    place_lng: float,
) -> list[dict[str, str]]:
    """Return OpenAI-compatible messages list for the chat-completions endpoint."""
    if style not in _SYSTEM_BY_STYLE:
        raise ValueError(f"unknown adventure style: {style!r}")

    system = _SYSTEM_BY_STYLE[style]

    description_line = (
        f"\nKnown context about this place: {place_description}"
        if place_description
        else ""
    )

    user = (
        f"Compose a mission for the operative known as {callsign}.\n\n"
        f"Target: {place_name} (a {place_category}) at coordinates "
        f"{place_lat:.5f}, {place_lng:.5f}.{description_line}\n\n"
        f"The operative will travel to this location, photograph it as proof, and "
        f"return. Write a mission briefing in your voice. Make it feel real, slightly "
        f"mysterious, and worth doing. Address {callsign} directly.\n\n"
        f"Respond with the JSON object as specified."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 4.4: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | grep -E "test_mission_prompts|PASSED|FAILED" | tail -8
```

Expected: 6 passed.

- [ ] **Step 4.5: Commit**

```bash
git add src/dispatchzero/services/mission_prompts.py tests/test_mission_prompts.py
git commit -m "feat: style-specific mission prompt builder (pulp/agency/guild) with JSON contract"
```

---

### Task 5: Ollama client (TDD with respx)

**Files:**
- Create: `src/dispatchzero/integrations/ollama.py`
- Create: `tests/test_integrations_ollama.py`

- [ ] **Step 5.1: Write failing tests**

Write to `tests/test_integrations_ollama.py`:

```python
import httpx
import pytest
import respx

from dispatchzero.integrations.ollama import OllamaClient, OllamaError


def _chat_response(content: str) -> dict:
    return {
        "id": "chatcmpl-test",
        "model": "gpt-oss:120b",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


@pytest.mark.asyncio
async def test_chat_returns_content_string():
    messages = [{"role": "user", "content": "hi"}]
    client = OllamaClient(api_key="test-key", base_url="https://ollama.example/v1", model="m")
    with respx.mock:
        respx.post("https://ollama.example/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_chat_response('{"x": 1}'))
        )
        out = await client.chat(messages)
    assert out == '{"x": 1}'


@pytest.mark.asyncio
async def test_chat_sends_bearer_auth_and_model():
    messages = [{"role": "user", "content": "hi"}]
    client = OllamaClient(api_key="my-secret", base_url="https://ollama.example/v1", model="m")
    with respx.mock:
        route = respx.post("https://ollama.example/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_chat_response("{}"))
        )
        await client.chat(messages)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer my-secret"
    import json
    body = json.loads(request.read())
    assert body["model"] == "m"
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_chat_retries_once_on_5xx():
    messages = [{"role": "user", "content": "hi"}]
    client = OllamaClient(api_key="k", base_url="https://ollama.example/v1", model="m")
    with respx.mock:
        route = respx.post("https://ollama.example/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, json=_chat_response("{}")),
            ]
        )
        out = await client.chat(messages)
    assert out == "{}"
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_chat_raises_after_two_5xx():
    messages = [{"role": "user", "content": "hi"}]
    client = OllamaClient(api_key="k", base_url="https://ollama.example/v1", model="m")
    with respx.mock:
        respx.post("https://ollama.example/v1/chat/completions").mock(
            return_value=httpx.Response(503)
        )
        with pytest.raises(OllamaError):
            await client.chat(messages)


@pytest.mark.asyncio
async def test_chat_raises_immediately_on_4xx():
    messages = [{"role": "user", "content": "hi"}]
    client = OllamaClient(api_key="bad", base_url="https://ollama.example/v1", model="m")
    with respx.mock:
        route = respx.post("https://ollama.example/v1/chat/completions").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        with pytest.raises(OllamaError):
            await client.chat(messages)
    assert route.call_count == 1  # no retry on 4xx


@pytest.mark.asyncio
async def test_chat_raises_when_no_api_key():
    client = OllamaClient(api_key="", base_url="https://ollama.example/v1", model="m")
    with pytest.raises(OllamaError, match="api key"):
        await client.chat([{"role": "user", "content": "x"}])
```

- [ ] **Step 5.2: Run, confirm fail**

```bash
./deploy/test.sh 2>&1 | grep -E "test_integrations_ollama|FAILED|PASSED" | tail -8
```

Expected: ImportError.

- [ ] **Step 5.3: Implement**

Write to `src/dispatchzero/integrations/ollama.py`:

```python
import httpx


class OllamaError(RuntimeError):
    """Raised when Ollama Cloud rejects the request or fails persistently."""


class OllamaClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int = 15,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._http = http_client or httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={
                "User-Agent": "dispatchzero/0.1 (trevor@johnsonfarms.us)",
            },
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """Call chat-completions in JSON mode. Returns the assistant's content string."""
        if not self._api_key:
            raise OllamaError("ollama api key is not configured")

        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.8,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        # One retry on 5xx / transport errors. None on 4xx.
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                r = await self._http.post(url, json=payload, headers=headers)
            except httpx.TransportError as e:
                last_exc = e
                if attempt == 2:
                    raise OllamaError(f"ollama transport failed: {e}") from e
                continue

            if r.status_code >= 500:
                if attempt == 2:
                    raise OllamaError(f"ollama 5xx: {r.status_code} {r.text[:200]}")
                continue
            if r.status_code >= 400:
                raise OllamaError(f"ollama 4xx: {r.status_code} {r.text[:200]}")

            data = r.json()
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as e:
                raise OllamaError(f"unexpected ollama response shape: {data}") from e

        # Unreachable, but appease type checkers.
        raise OllamaError(f"ollama failed after retries: {last_exc}")
```

- [ ] **Step 5.4: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | grep -E "test_integrations_ollama|PASSED|FAILED" | tail -8
```

Expected: 6 passed.

- [ ] **Step 5.5: Commit**

```bash
git add src/dispatchzero/integrations/ollama.py tests/test_integrations_ollama.py
git commit -m "feat: ollama cloud client (json mode, bearer auth, one retry on 5xx)"
```

---

### Task 6: Mission service — library hit + fresh generation (TDD)

**Files:**
- Create: `src/dispatchzero/services/missions.py`
- Create: `tests/test_missions_service.py`

- [ ] **Step 6.1: Write failing tests**

Write to `tests/test_missions_service.py`:

```python
import json
import uuid

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.models import Mission, Place, User
from dispatchzero.services.missions import MissionGenerationError, get_or_generate_mission


async def _make_user_and_place(db: AsyncSession) -> tuple[User, Place]:
    user = User(
        callsign="Trevor",
        callsign_lower="trevor",
        password_hash="x",
        adventure_style="agency",
    )
    place = Place(
        osm_type="node",
        osm_id=1,
        name="Test Sculpture",
        category="sculpture",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)",
        tags={},
        description="A test piece.",
    )
    db.add_all([user, place])
    await db.commit()
    await db.refresh(user)
    await db.refresh(place)
    return user, place


def _ollama_response(payload: dict) -> dict:
    return {
        "id": "chatcmpl-test",
        "model": "gpt-oss:120b",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(payload)},
                "finish_reason": "stop",
            }
        ],
    }


@pytest.mark.asyncio
async def test_generate_calls_ollama_and_persists_mission(db_session, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    payload = {
        "dispatch_summary": "Document the Test Sculpture.",
        "briefing_text": "Travel to the Test Sculpture and capture proof of its existence.",
        "clue": "Look for the brass plaque at the base.",
        "badge_framing": "First Sculpture Documented",
    }
    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response(payload))
        )
        mission = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="agency"
        )

    assert mission.dispatch_summary == "Document the Test Sculpture."
    assert mission.adventure_style == "agency"
    assert mission.ai_model == "gpt-oss:120b"
    rows = (await db_session.execute(select(Mission))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_library_hit_does_not_call_ollama(db_session, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    payload = {
        "dispatch_summary": "First.",
        "briefing_text": "Body.",
        "clue": None,
        "badge_framing": None,
    }
    with respx.mock:
        route = respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response(payload))
        )
        m1 = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="agency"
        )
        m2 = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="agency"
        )
    assert m1.id == m2.id
    assert route.call_count == 1  # second call hit library


@pytest.mark.asyncio
async def test_different_styles_generate_different_missions(db_session, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    payload = {
        "dispatch_summary": "X",
        "briefing_text": "Y",
        "clue": None,
        "badge_framing": None,
    }
    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response(payload))
        )
        m1 = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="agency"
        )
        m2 = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style="pulp"
        )
    assert m1.id != m2.id


@pytest.mark.asyncio
async def test_unknown_place_raises(db_session):
    user = User(
        callsign="X", callsign_lower="x", password_hash="x", adventure_style="agency",
    )
    db_session.add(user)
    await db_session.commit()

    with pytest.raises(MissionGenerationError, match="place"):
        await get_or_generate_mission(
            db=db_session, user=user, place_id=uuid.uuid4(), adventure_style="agency"
        )


@pytest.mark.asyncio
async def test_malformed_ollama_json_raises(db_session, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)

    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response({"wrong_shape": True}))
        )
        with pytest.raises(MissionGenerationError):
            await get_or_generate_mission(
                db=db_session, user=user, place_id=place.id, adventure_style="agency"
            )


@pytest.mark.asyncio
async def test_default_style_falls_back_to_user_profile(db_session, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    user, place = await _make_user_and_place(db_session)
    # user.adventure_style is "agency"
    payload = {
        "dispatch_summary": "A",
        "briefing_text": "B",
        "clue": None,
        "badge_framing": None,
    }
    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_response(payload))
        )
        mission = await get_or_generate_mission(
            db=db_session, user=user, place_id=place.id, adventure_style=None
        )
    assert mission.adventure_style == "agency"
```

- [ ] **Step 6.2: Run, confirm fail**

```bash
./deploy/test.sh 2>&1 | grep -E "test_missions_service|FAILED|PASSED" | tail -8
```

Expected: ImportError.

- [ ] **Step 6.3: Implement**

Write to `src/dispatchzero/services/missions.py`:

```python
import uuid
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.config import get_settings
from dispatchzero.integrations.ollama import OllamaClient, OllamaError
from dispatchzero.models import Mission, MissionStatus, Place, User
from dispatchzero.schemas.missions import MissionContent
from dispatchzero.services.mission_prompts import build_mission_prompt

AdventureStyle = Literal["pulp", "agency", "guild"]


class MissionGenerationError(RuntimeError):
    """Raised when a mission cannot be produced (place not found, Ollama failure, validation failure)."""


async def get_or_generate_mission(
    *,
    db: AsyncSession,
    user: User,
    place_id: uuid.UUID,
    adventure_style: AdventureStyle | None,
) -> Mission:
    """Library hit if available, otherwise generate fresh via Ollama and persist."""
    style = adventure_style or user.adventure_style

    place = (
        await db.execute(select(Place).where(Place.id == place_id))
    ).scalar_one_or_none()
    if place is None:
        raise MissionGenerationError(f"place {place_id} not found")

    # Library hit: best-loved active mission for this place + style
    library_hit = await _library_lookup(db, place_id=place_id, style=style)
    if library_hit is not None:
        return library_hit

    # Fresh generation
    settings = get_settings()
    client = OllamaClient(
        api_key=settings.ollama_api_key,
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    try:
        messages = build_mission_prompt(
            style=style,
            callsign=user.callsign,
            place_name=place.name or "an unnamed place",
            place_category=place.category,
            place_description=place.description,
            place_lat=0.0,  # placeholder — we don't ship raw coordinates to the LLM
            place_lng=0.0,
        )
        try:
            raw = await client.chat(messages)
        except OllamaError as e:
            raise MissionGenerationError(f"ollama call failed: {e}") from e
    finally:
        await client.aclose()

    try:
        content = MissionContent.model_validate_json(raw)
    except ValidationError as e:
        raise MissionGenerationError(f"ollama returned invalid mission shape: {e}") from e

    mission = Mission(
        place_id=place.id,
        adventure_style=style,
        dispatch_summary=content.dispatch_summary,
        briefing_text=content.briefing_text,
        clue=content.clue,
        badge_framing=content.badge_framing,
        ai_model=settings.ollama_model,
    )
    db.add(mission)
    await db.commit()
    await db.refresh(mission)
    return mission


async def _library_lookup(
    db: AsyncSession, *, place_id: uuid.UUID, style: str
) -> Mission | None:
    """Return the best-loved still-active mission for this place+style, if any."""
    stmt = (
        select(Mission)
        .where(
            Mission.place_id == place_id,
            Mission.adventure_style == style,
            Mission.status == MissionStatus.ACTIVE.value,
            Mission.mission_thumbs_down < 3,
        )
        .order_by(Mission.mission_thumbs_up.desc(), Mission.created_at.asc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()
```

> **Note on coordinates:** The prompt builder accepts `place_lat`/`place_lng` for testability and possible future use, but we currently pass `0.0, 0.0` so the LLM doesn't see exact coords (no need; the place name + description carry the narrative weight). If we ever want the LLM to write "approximately 200 meters from the river," we can pass real coordinates here without changing the prompt builder.

- [ ] **Step 6.4: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | grep -E "test_missions_service|PASSED|FAILED" | tail -8
```

Expected: 6 passed.

- [ ] **Step 6.5: Commit**

```bash
git add src/dispatchzero/services/missions.py tests/test_missions_service.py
git commit -m "feat: mission generation service (library hit + ollama call + persist)"
```

---

### Task 7: POST /missions/generate route + integration tests

**Files:**
- Create: `src/dispatchzero/missions/__init__.py`
- Create: `src/dispatchzero/missions/routes.py`
- Modify: `src/dispatchzero/main.py`
- Create: `tests/test_missions_routes.py`

- [ ] **Step 7.1: Write failing tests**

Write to `tests/test_missions_routes.py`:

```python
import json
import uuid

import httpx
import pytest
import respx
from sqlalchemy import select

from dispatchzero.models import Mission, Place

SIGNUP = {
    "callsign": "Hunter",
    "password": "long-enough-password",
    "adventure_style": "agency",
}


def _ollama_payload() -> dict:
    return {
        "id": "chatcmpl-test",
        "model": "gpt-oss:120b",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "dispatch_summary": "A two-line preview.",
                            "briefing_text": "The full briefing body.",
                            "clue": "Look up.",
                            "badge_framing": "First Mural",
                        }
                    ),
                },
                "finish_reason": "stop",
            }
        ],
    }


async def _make_place(db_session) -> Place:
    place = Place(
        osm_type="node",
        osm_id=42,
        name="Test Mural",
        category="mural",
        coordinates="SRID=4326;POINT(-117.4198 47.6605)",
        tags={},
    )
    db_session.add(place)
    await db_session.commit()
    await db_session.refresh(place)
    return place


@pytest.mark.asyncio
async def test_generate_requires_auth(client, db_session, redis_client):
    client.cookies.clear()
    r = await client.post("/missions/generate", json={"place_id": str(uuid.uuid4())})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_generate_returns_mission(client, db_session, redis_client, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    await client.post("/auth/signup", json=SIGNUP)
    place = await _make_place(db_session)

    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )
        r = await client.post("/missions/generate", json={"place_id": str(place.id)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dispatch_summary"] == "A two-line preview."
    assert body["adventure_style"] == "agency"


@pytest.mark.asyncio
async def test_generate_returns_library_hit_on_repeat_call(
    client, db_session, redis_client, monkeypatch
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    await client.post("/auth/signup", json=SIGNUP)
    place = await _make_place(db_session)

    with respx.mock:
        route = respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )
        r1 = await client.post("/missions/generate", json={"place_id": str(place.id)})
        r2 = await client.post("/missions/generate", json={"place_id": str(place.id)})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_generate_returns_404_for_unknown_place(
    client, db_session, redis_client, monkeypatch
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    await client.post("/auth/signup", json=SIGNUP)

    r = await client.post("/missions/generate", json={"place_id": str(uuid.uuid4())})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_generate_returns_503_when_ollama_unavailable(
    client, db_session, redis_client, monkeypatch
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    await client.post("/auth/signup", json=SIGNUP)
    place = await _make_place(db_session)

    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(503)
        )
        r = await client.post("/missions/generate", json={"place_id": str(place.id)})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_generate_overrides_style_when_provided(
    client, db_session, redis_client, monkeypatch
):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    await client.post("/auth/signup", json=SIGNUP)  # user is "agency"
    place = await _make_place(db_session)

    with respx.mock:
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )
        r = await client.post(
            "/missions/generate",
            json={"place_id": str(place.id), "adventure_style": "pulp"},
        )
    assert r.status_code == 200
    assert r.json()["adventure_style"] == "pulp"
```

- [ ] **Step 7.2: Implement the route**

Write to `src/dispatchzero/missions/__init__.py`:

```python
```
(empty)

Write to `src/dispatchzero/missions/routes.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from dispatchzero.auth.deps import current_user
from dispatchzero.db import get_session
from dispatchzero.models import User
from dispatchzero.schemas.missions import MissionGenerateIn, MissionOut
from dispatchzero.services.missions import (
    MissionGenerationError,
    get_or_generate_mission,
)

router = APIRouter(prefix="/missions", tags=["missions"])


@router.post("/generate", response_model=MissionOut)
async def generate(
    payload: MissionGenerateIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MissionOut:
    try:
        mission = await get_or_generate_mission(
            db=db,
            user=user,
            place_id=payload.place_id,
            adventure_style=payload.adventure_style,
        )
    except MissionGenerationError as e:
        msg = str(e).lower()
        if "not found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
        # Ollama failure or validation failure → 503 in-character
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the dispatch line is unreliable, agent — try again",
        ) from e

    return MissionOut(
        id=mission.id,
        place_id=mission.place_id,
        adventure_style=mission.adventure_style,
        dispatch_summary=mission.dispatch_summary,
        briefing_text=mission.briefing_text,
        clue=mission.clue,
        badge_framing=mission.badge_framing,
        audio_url=mission.audio_url,
        ai_model=mission.ai_model,
        status=mission.status,
    )
```

- [ ] **Step 7.3: Mount the router**

In `src/dispatchzero/main.py`:

```python
from fastapi import FastAPI

from dispatchzero.auth.routes import router as auth_router
from dispatchzero.missions.routes import router as missions_router
from dispatchzero.places.routes import router as places_router

app = FastAPI(title="Dispatch Zero")
app.include_router(auth_router)
app.include_router(places_router)
app.include_router(missions_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "dispatch-zero", "status": "operational"}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 7.4: Run, confirm pass**

```bash
./deploy/test.sh 2>&1 | tail -10
```

Expected: all tests pass; 6 new in `test_missions_routes.py`.

- [ ] **Step 7.5: Commit**

```bash
git add src/dispatchzero/missions src/dispatchzero/main.py tests/test_missions_routes.py
git commit -m "feat: POST /missions/generate endpoint with auth + 404/503 mapping"
```

---

### Task 8: Set OLLAMA_API_KEY on VPS, deploy, smoke-verify against real Ollama

> **Prerequisite:** Trevor must have an Ollama Cloud account and an API key. If not, this is the time to create one at https://ollama.com (free tier is fine for the smoke test).

- [ ] **Step 8.1: Add OLLAMA_API_KEY to prod `.env`**

```bash
ssh root@89.167.39.152 "
  if grep -q '^OLLAMA_API_KEY=' /opt/dispatchzero/.env; then
    echo 'OLLAMA_API_KEY already present'
  else
    echo 'OLLAMA_API_KEY=PASTE_YOUR_KEY_HERE' >> /opt/dispatchzero/.env
    echo 'added placeholder; edit the file before deploying'
  fi
  echo 'Current OLLAMA-related env (redacted):'
  grep '^OLLAMA' /opt/dispatchzero/.env | sed 's/=.*\$/=<redacted>/'
"
```

If the placeholder was added, edit the file (`vi /opt/dispatchzero/.env`) and replace `PASTE_YOUR_KEY_HERE` with the real Ollama Cloud API key. Save.

- [ ] **Step 8.2: Deploy**

```bash
./deploy/deploy.sh
```

Expected: deploy succeeds, alembic upgrades to `0004`.

- [ ] **Step 8.3: Verify migration**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app alembic current"
```

Expected: `0004 (head)`.

- [ ] **Step 8.4: Curl signup → /places/nearby (Spokane) → grab a place_id → /missions/generate**

```bash
COOKIES=$(mktemp)

# Signup
curl -sS -c "$COOKIES" -X POST https://dispatchzero.ataary.com/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"callsign":"smoketest_p4","password":"smoketest-very-long-password","adventure_style":"agency"}' \
  > /dev/null

# Get a place_id from the discovery endpoint (Garbage Goat area in Spokane)
PLACE_ID=$(curl -sS -b "$COOKIES" \
  "https://dispatchzero.ataary.com/places/nearby?lat=47.6605131&lng=-117.4197590&radius_m=2000&limit=1" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)[0]['id'])")
echo "place_id: $PLACE_ID"
echo

echo "===== generate (Agency style) ====="
curl -sS -b "$COOKIES" -X POST https://dispatchzero.ataary.com/missions/generate \
  -H "Content-Type: application/json" \
  -d "{\"place_id\":\"$PLACE_ID\"}" \
  | python3 -m json.tool
echo

echo "===== second call should be library hit (same id, no new Ollama call) ====="
curl -sS -b "$COOKIES" -X POST https://dispatchzero.ataary.com/missions/generate \
  -H "Content-Type: application/json" \
  -d "{\"place_id\":\"$PLACE_ID\"}" \
  | python3 -m json.tool
echo

echo "===== generate Pulp style for the same place ====="
curl -sS -b "$COOKIES" -X POST https://dispatchzero.ataary.com/missions/generate \
  -H "Content-Type: application/json" \
  -d "{\"place_id\":\"$PLACE_ID\", \"adventure_style\":\"pulp\"}" \
  | python3 -m json.tool

rm -f "$COOKIES"
```

Expected:
- First Agency generate: returns a mission with non-empty `dispatch_summary` and `briefing_text`. Briefing reads in clinical/operative voice and signs as `— Zero`. (NOT Vale/Ashford/Warden.)
- Second Agency generate for same place: identical `id` (library hit).
- Pulp generate: different `id`, briefing reads in warm/expedition voice, also signs as `— Zero`.

- [ ] **Step 8.5: Inspect missions table**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -c \"SELECT adventure_style, ai_model, LEFT(dispatch_summary, 60) AS preview FROM missions ORDER BY created_at;\""
```

Expected: 2 rows (one agency, one pulp), both with the configured model name in `ai_model`.

- [ ] **Step 8.6: Cleanup smoketest user (do NOT delete missions — they're real library entries)**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U dispatchzero -d dispatchzero -c \"DELETE FROM user_place_history WHERE user_id IN (SELECT id FROM users WHERE callsign_lower = 'smoketest_p4'); DELETE FROM users WHERE callsign_lower = 'smoketest_p4';\""
```

(Missions stay — they're now library entries that will be served to real users.)

- [ ] **Step 8.7: Confirm Paperclip and resources still healthy**

```bash
ssh root@89.167.39.152 "systemctl is-active paperclip.service && free -h | head -2 && df -h /"
```

Expected: `active`, RAM available > 1.5 GB, disk used < 85%.

---

## Phase 4 — Definition of Done

- All tests pass via `./deploy/test.sh`.
- Production smoke (signup → /places/nearby → /missions/generate) returns a real mission JSON that reads in-character for the chosen style.
- Mission signs as `— Zero` (NOT Vale/Ashford/Warden).
- Second call for same place + style returns the same mission id (library hit; no second Ollama call).
- Different style for the same place generates a fresh mission (different id).
- Migration `0004` applied; `missions` and `mission_stops` tables exist.
- 503 response returned when Ollama is unreachable / returns malformed JSON.
- Paperclip restart count unchanged.

---

## Critical Files To Be Created In Phase 4

| File | Purpose |
|---|---|
| `src/dispatchzero/integrations/ollama.py` | Ollama Cloud HTTP client (JSON mode + retry) |
| `src/dispatchzero/models/mission.py` | Mission ORM model |
| `src/dispatchzero/models/mission_stop.py` | MissionStop ORM model |
| `src/dispatchzero/services/mission_prompts.py` | Style-specific prompt builder |
| `src/dispatchzero/services/missions.py` | Library lookup + generation orchestrator |
| `src/dispatchzero/schemas/missions.py` | MissionContent (LLM output), MissionGenerateIn, MissionOut |
| `src/dispatchzero/missions/routes.py` | POST /missions/generate |
| `alembic/versions/0004_missions.py` | Migration (ONE op.execute() per statement) |

---

## Open Decisions (default in plan, override before starting)

| Decision | Default | Where to change |
|---|---|---|
| Ollama Cloud model | `gpt-oss:120b` | `Settings.ollama_model` (env: `OLLAMA_MODEL`) |
| Ollama base URL | `https://ollama.com/v1` (OpenAI-compat) | `Settings.ollama_base_url` |
| Timeout | 15s total per attempt | `Settings.ollama_timeout_seconds` |
| Temperature | 0.8 | `OllamaClient.chat()` payload |
| Sync request handling | Yes | Move to background queue in Phase 12 if needed |
| Per-user rate limit | None in v1 | Add Redis limiter in Phase 14 (launch hardening) |
| Mission length caps | dispatch ≤ 400, briefing ≤ 2200 chars | `MissionContent` Field constraints |
| What happens on Ollama 503 | Return 503 to client with in-character message | `missions/routes.py` exception mapping |

---

## What Comes Next After Phase 4

Phase 5 — Mission flow API. With place discovery (Phase 3) and mission generation (Phase 4) live, Phase 5 wires the full mission lifecycle: request → accept → capture (with photo + GPS verification + EXIF freshness) → debrief → rate. Adds the Completion model and the photo-handling pipeline. The Phase 5 plan will be written using the same skill at the end of Phase 4.

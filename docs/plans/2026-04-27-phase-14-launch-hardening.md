# Phase 14: Launch Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End of Phase 14 = the URL is safe to share with people who might forward it. Runaway costs are bounded, user data is recoverable from off-host, errors are visible without grepping logs, and outages are detected before users complain.

**Architecture:** Six independent hardening layers, each shippable on its own. Most live in the backend (rate limits, Sentry, log rotation) or in compose (backup sidecar, log driver). Two require external account setup (Backblaze B2 for off-host backups, UptimeRobot for external uptime). One is purely UI (beta banner). Tasks are ordered by impact-on-launch-readiness — top items must ship before sharing the URL; bottom items are polish.

**Tech stack:** FastAPI rate-limit middleware (Redis-backed, same pattern as `/auth/login`), `pg_dump` in a small alpine sidecar with rclone to B2, `sentry-sdk[fastapi]` (hosted free tier), Docker `json-file` log driver with size+rotation, ntfy.sh for disk alerts (free, no signup), UptimeRobot free tier for external uptime, env-toggled banner div on the home screen.

**Threat model.** Trevor is sharing the URL with a small pool of testers. The realistic risks are:
1. **Cost runaway** — Ollama Cloud is metered per call. A bug in the client, a malicious actor, or just one tester writing a script could rack up bills overnight. *Rate limiting is therefore the highest-priority task.*
2. **Data loss** — Postgres volume corruption or accidental `docker volume rm` would destroy every user's history. Off-box backups are the floor.
3. **Silent failures** — without Sentry + uptime monitoring, problems show up as "Trevor's friends giving up." Both make problems visible.
4. **Disk fill** — uncapped logs + accumulating photo uploads could fill `/` and crash the host. Log rotation + disk alert handle this.

Not in scope (would be over-engineering for a small-pool launch):
- DDoS protection (Cloudflare in front of Caddy) — defer until tester pool grows
- WAF rules — defer
- Auth lockout / 2FA — defer; callsign+password is the agreed v1 model
- HSM key storage — defer; SESSION_SECRET on disk is fine for a single-host setup

---

## Decision defaults (override before starting)

| Decision | Default | Why |
|---|---|---|
| Off-box backup target | Backblaze B2 free tier (10 GB free, $6/TB/mo above) | Cheaper than S3, generous free tier, well-documented rclone path. |
| Backup tool | `rclone` invoked from a sidecar container, scheduled via cron-in-container | Avoids systemd timer ops on host; everything stays in compose; survives `docker compose down/up`. |
| Backup frequency | Postgres: nightly at 03:00 UTC + 7-day local rotation + 30-day off-box rotation. Photos: nightly off-box only (skip local rotation since they're already on disk). | Daily granularity is enough for a small-pool MVP. RPO of ~24h is acceptable. |
| Error tracking | Sentry hosted, free Developer tier (5k errors/month) | Lower ops cost than self-hosting Glitchtip. Generous enough for v1 traffic. |
| Disk alert | ntfy.sh — public topic, hardcoded URL, threshold 85% on `/` | Zero signup, zero infra. Trevor subscribes on phone via the ntfy app. |
| Uptime monitoring | UptimeRobot free tier, 5-minute interval against `/healthz` | External viewpoint; complements internal monitoring. Free 50 monitors, more than enough. |
| Rate-limit `/missions/request` | 50/day per user | Generous for a tester walking around a city all day; tight enough to bound a runaway client. |
| Rate-limit `/missions/generate` | 50/day per user (shared budget with /request? no — separate, since /request internally calls /generate but library hits don't burn budget) | Keep them separate so Ollama-only surface is independently capped. |
| Rate-limit `/auth/signup` | 10 per IP per hour | Keeps spam signups bounded without blocking a friend group on shared NAT. |
| Beta banner | env-controlled (`SHOW_BETA_BANNER=true`), shows on Splash + Home | Simple toggle Trevor can flip before public launch. |

---

## Repo layout deltas

```
dispatch-zero/
├── src/dispatchzero/
│   ├── config.py                       # MODIFIED — add SENTRY_DSN, SHOW_BETA_BANNER, rate-limit caps
│   ├── main.py                         # MODIFIED — Sentry init, banner endpoint
│   ├── auth/routes.py                  # MODIFIED — IP rate-limit on /auth/signup
│   ├── missions/routes.py              # MODIFIED — per-user rate-limit on /missions/request and /missions/generate
│   └── ratelimit.py                    # NEW — shared rate-limit helper (Redis-backed, reuses login pattern)
├── tests/
│   ├── test_ratelimit.py               # NEW — unit + integration coverage of the rate limiter
│   ├── test_missions_routes.py         # MODIFIED — assert rate-limit kicks in
│   └── test_auth_routes.py             # MODIFIED — assert signup IP rate-limit
├── frontend/static/js/screens/
│   ├── splash.js                       # MODIFIED — render banner if /config returns SHOW_BETA_BANNER
│   └── home.js                         # MODIFIED — same
├── ops/
│   ├── backup/
│   │   ├── Dockerfile                  # NEW — alpine + postgresql-client + rclone + crond
│   │   ├── entrypoint.sh               # NEW — installs the cron, starts crond in foreground
│   │   ├── nightly-backup.sh           # NEW — pg_dump, rotate local, push to B2
│   │   └── rclone.conf.example         # NEW — template for B2 creds (real one is mounted from host)
│   ├── disk-alert/
│   │   ├── Dockerfile                  # NEW — alpine + curl + crond
│   │   ├── entrypoint.sh               # NEW — cron-installer + crond
│   │   └── check-disk.sh               # NEW — df check, ntfy POST if > threshold
│   └── README.md                       # NEW — operator runbook (B2 setup, ntfy topic, Sentry DSN, UptimeRobot)
├── docker-compose.prod.yml             # MODIFIED — add backup + disk-alert services, log-driver options on all services
├── .env.example                        # MODIFIED — add SENTRY_DSN, SHOW_BETA_BANNER, B2 creds, ntfy topic
└── pyproject.toml                      # MODIFIED — add sentry-sdk[fastapi]
```

---

## Order of operations

Tasks are independent. Recommended order (by launch-readiness impact):

1. **Task 1 — Rate limiting** (blocks runaway costs; ship first)
2. **Task 2 — Backup pipeline** (protects user data; ship before sharing)
3. **Task 3 — Sentry integration** (visibility; ship before sharing)
4. **Task 4 — Log rotation + disk alert** (disk safety; can ship after sharing)
5. **Task 5 — External uptime monitoring** (no code; manual setup, can do anytime)
6. **Task 6 — Beta banner** (polish; ship anytime)

Each task ends in a deployable, testable state. Stop after Task 3 and you're already safe to share with testers.

---

## Task 1: Rate-limit the expensive endpoints

**Files:**
- Create: `src/dispatchzero/ratelimit.py`
- Create: `tests/test_ratelimit.py`
- Modify: `src/dispatchzero/config.py`
- Modify: `src/dispatchzero/missions/routes.py`
- Modify: `src/dispatchzero/auth/routes.py`
- Modify: `tests/test_missions_routes.py` (or `test_missions_flow_routes.py`)
- Modify: `tests/test_auth_routes.py`
- Modify: `.env.example`

### Background

Phase 2 already has a Redis-backed rate limit on `/auth/login`. We're going to extract that pattern into a reusable helper, then apply it to three endpoints with three different keying strategies:
- `/missions/request`: keyed by user id (caller is authed)
- `/missions/generate`: keyed by user id (same)
- `/auth/signup`: keyed by client IP (no user yet)

Redis key format: `rl:{scope}:{identifier}:{epoch_window_index}`. We use a sliding-fixed-window: a counter that resets every N seconds, with the window aligned to wall-clock seconds (simpler than a true sliding window, and good enough for this).

- [ ] **Step 1.1: Skim the existing /auth/login limit to see the current pattern**

```bash
grep -n -A 30 "rate_limit\|login_attempt\|LOGIN_ATTEMPT" src/dispatchzero/auth/*.py
```

Note the key prefix, TTL, increment strategy. We'll generalize it.

- [ ] **Step 1.2: Write the failing unit test for the rate limiter**

Write to `tests/test_ratelimit.py`:

```python
import pytest

from dispatchzero.ratelimit import check_and_increment, RateLimitExceeded


@pytest.mark.asyncio
async def test_first_call_in_window_passes(redis_client):
    await check_and_increment(
        redis=redis_client, scope="test", identifier="user-1",
        max_count=3, window_seconds=60,
    )


@pytest.mark.asyncio
async def test_caps_at_max_count(redis_client):
    for _ in range(3):
        await check_and_increment(
            redis=redis_client, scope="test", identifier="user-2",
            max_count=3, window_seconds=60,
        )
    with pytest.raises(RateLimitExceeded) as exc_info:
        await check_and_increment(
            redis=redis_client, scope="test", identifier="user-2",
            max_count=3, window_seconds=60,
        )
    assert exc_info.value.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_separate_identifiers_have_separate_buckets(redis_client):
    for _ in range(3):
        await check_and_increment(
            redis=redis_client, scope="test", identifier="user-A",
            max_count=3, window_seconds=60,
        )
    # user-B is untouched
    await check_and_increment(
        redis=redis_client, scope="test", identifier="user-B",
        max_count=3, window_seconds=60,
    )


@pytest.mark.asyncio
async def test_separate_scopes_have_separate_buckets(redis_client):
    for _ in range(3):
        await check_and_increment(
            redis=redis_client, scope="scope-A", identifier="user-1",
            max_count=3, window_seconds=60,
        )
    # scope-B is untouched
    await check_and_increment(
        redis=redis_client, scope="scope-B", identifier="user-1",
        max_count=3, window_seconds=60,
    )
```

- [ ] **Step 1.3: Run the test to confirm it fails on import**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest tests/test_ratelimit.py -v"
```

Expected: `ImportError` on `dispatchzero.ratelimit`.

- [ ] **Step 1.4: Implement the rate-limiter helper**

Write to `src/dispatchzero/ratelimit.py`:

```python
"""Redis-backed fixed-window rate limiter.

Same pattern as the /auth/login limiter from Phase 2, generalized so we can
apply it to /missions/request, /missions/generate, and /auth/signup.

Window strategy: fixed bucket aligned to wall-clock seconds. Each unique
(scope, identifier) gets its own counter that resets every `window_seconds`.
Trade-off: a caller can do up to `2 * max_count` in any rolling 2*window
period if they straddle the boundary. Acceptable for our caps (10s of calls,
not 1000s).

Atomic via INCR (returns post-increment count) + EXPIRE (idempotent — only
sets TTL if not already set).
"""
import time

import redis.asyncio as aioredis


class RateLimitExceeded(RuntimeError):
    """Raised when the caller has exhausted their bucket. Carries retry_after."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limit exceeded; retry in {retry_after_seconds}s")


async def check_and_increment(
    *,
    redis: aioredis.Redis,
    scope: str,
    identifier: str,
    max_count: int,
    window_seconds: int,
) -> None:
    """Atomically increment the bucket counter; raise if over the cap.

    `scope` is a short label like 'mission_request' or 'signup_ip'.
    `identifier` is the caller fingerprint — user id, IP, etc.
    """
    now = int(time.time())
    bucket = now // window_seconds
    key = f"rl:{scope}:{identifier}:{bucket}"

    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()

    count = int(results[0])
    if count > max_count:
        # Time until this bucket rolls over.
        retry_after = window_seconds - (now % window_seconds)
        raise RateLimitExceeded(retry_after_seconds=max(retry_after, 1))
```

- [ ] **Step 1.5: Run the unit tests to confirm they pass**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest tests/test_ratelimit.py -v"
```

Expected: 4 passed.

- [ ] **Step 1.6: Add per-endpoint caps to settings**

Modify `src/dispatchzero/config.py` — add three new fields to the `Settings` class:

```python
    # Rate limits — bounds on expensive endpoints.
    # Format: max_count over window_seconds.
    rate_limit_mission_request_per_day: int = 50
    rate_limit_mission_generate_per_day: int = 50
    rate_limit_signup_per_ip_per_hour: int = 10
```

These have sensible defaults so .env doesn't strictly need them; override via env if you want to tune.

- [ ] **Step 1.7: Update .env.example to document them**

Modify `.env.example`, add at the bottom:

```
# Rate limits (override only if defaults need tuning)
RATE_LIMIT_MISSION_REQUEST_PER_DAY=50
RATE_LIMIT_MISSION_GENERATE_PER_DAY=50
RATE_LIMIT_SIGNUP_PER_IP_PER_HOUR=10
```

- [ ] **Step 1.8: Wire `/missions/request` to the limiter (TDD)**

First, add a failing test. Append to `tests/test_missions_flow_routes.py`:

```python
@pytest.mark.asyncio
async def test_missions_request_rate_limit_kicks_in(
    client, db_session, redis_client, monkeypatch,
):
    """After 50 successful /missions/request calls, the 51st returns 429."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_MODEL", "gpt-oss:120b")
    # Tiny cap for the test
    monkeypatch.setenv("RATE_LIMIT_MISSION_REQUEST_PER_DAY", "2")

    await client.post("/auth/signup", json=SIGNUP)

    with respx.mock:
        respx.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json=_overpass_one())
        )
        respx.post("https://ollama.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_ollama_payload())
        )

        for _ in range(2):
            r = await client.post("/missions/request", json={
                "lat": 47.6605, "lng": -117.4198, "radius_m": 2000,
            })
            assert r.status_code == 200, r.text

        # 3rd call hits the cap
        r = await client.post("/missions/request", json={
            "lat": 47.6605, "lng": -117.4198, "radius_m": 2000,
        })
    assert r.status_code == 429, r.text
    assert "Retry-After" in r.headers
```

Run it: `pytest tests/test_missions_flow_routes.py::test_missions_request_rate_limit_kicks_in -v` → should FAIL because no rate limit is wired yet.

- [ ] **Step 1.9: Wire the limiter into `/missions/request` and `/missions/generate`**

Modify `src/dispatchzero/missions/routes.py`. Add the import:

```python
from dispatchzero.ratelimit import RateLimitExceeded, check_and_increment
```

In `request_mission`, just after `redis: Annotated[aioredis.Redis, Depends(_get_redis)],` is bound and before `tiers = ...`:

```python
    settings = get_settings()
    try:
        await check_and_increment(
            redis=redis, scope="mission_request",
            identifier=str(user.id),
            max_count=settings.rate_limit_mission_request_per_day,
            window_seconds=86400,
        )
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests, agent — stand by",
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e
```

(`get_settings` is already imported at the top of the module.)

Apply the same pattern in the `generate` handler — same scope-name `mission_generate`, same window, but use `settings.rate_limit_mission_generate_per_day`. Note that `generate` isn't currently injecting the redis client — add it as a dependency:

```python
@router.post("/generate", response_model=MissionOut)
async def generate(
    payload: MissionGenerateIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[aioredis.Redis, Depends(_get_redis)],
) -> MissionOut:
    settings = get_settings()
    try:
        await check_and_increment(
            redis=redis, scope="mission_generate",
            identifier=str(user.id),
            max_count=settings.rate_limit_mission_generate_per_day,
            window_seconds=86400,
        )
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests, agent — stand by",
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e
    # ... existing code follows unchanged
```

- [ ] **Step 1.10: Re-run the test, confirm it passes**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest tests/test_missions_flow_routes.py -v"
```

Expected: all green, including the new rate-limit test.

- [ ] **Step 1.11: Add IP-based rate limit to `/auth/signup` (TDD)**

First the failing test. Append to `tests/test_auth_routes.py`:

```python
@pytest.mark.asyncio
async def test_signup_rate_limited_per_ip(client, db_session, redis_client, monkeypatch):
    """11th signup from the same IP within an hour returns 429."""
    monkeypatch.setenv("RATE_LIMIT_SIGNUP_PER_IP_PER_HOUR", "3")
    for i in range(3):
        r = await client.post("/auth/signup", json={
            "callsign": f"AgentX{i}",
            "password": "long-enough-password",
            "adventure_style": "agency",
        })
        assert r.status_code == 201, r.text
    # 4th hits the cap
    r = await client.post("/auth/signup", json={
        "callsign": "AgentXN",
        "password": "long-enough-password",
        "adventure_style": "agency",
    })
    assert r.status_code == 429
```

Run it — should FAIL.

Then modify `src/dispatchzero/auth/routes.py` — in the signup handler, import the limiter and inject the redis dependency (probably already injected for the login limiter):

```python
from fastapi import Request

# ... in the signup function:
async def signup(
    payload: SignupIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[aioredis.Redis, Depends(_get_redis)],
) -> ...:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    try:
        await check_and_increment(
            redis=redis, scope="signup_ip",
            identifier=client_ip,
            max_count=settings.rate_limit_signup_per_ip_per_hour,
            window_seconds=3600,
        )
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests — try again later",
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e
    # ... existing signup logic
```

Note: in production behind Caddy, `request.client.host` will be Caddy's IP, not the user's. Caddy needs to set `X-Forwarded-For`. Check the existing `_get_redis` dep / `current_user` middleware to see how the login limiter (if it exists) handles this. If it doesn't, add a small helper:

```python
def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first IP in the list (the original client).
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
```

And use `_client_ip(request)` instead of `request.client.host`.

- [ ] **Step 1.12: Verify Caddyfile sets X-Forwarded-For**

```bash
grep -i "forwarded\|trusted" Caddyfile
```

Caddy sets `X-Forwarded-For` automatically when reverse-proxying. If you see no overrides, you're good. If you see `header_up X-Forwarded-For ""` or similar, that's a problem — fix it.

- [ ] **Step 1.13: Run all tests to ensure nothing regressed**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest"
```

Expected: all green.

- [ ] **Step 1.14: Commit**

```bash
git add src/dispatchzero/ratelimit.py src/dispatchzero/config.py \
        src/dispatchzero/missions/routes.py src/dispatchzero/auth/routes.py \
        tests/test_ratelimit.py tests/test_missions_flow_routes.py \
        tests/test_auth_routes.py .env.example
git commit -m "feat: rate-limit /missions/request, /missions/generate, /auth/signup

Per-user daily caps on the two Ollama-burning endpoints; per-IP hourly cap
on signup to bound spam. Reusable helper in dispatchzero.ratelimit; same
fixed-window-counter pattern as the existing /auth/login limit.

Defaults: 50/day per user for both mission endpoints, 10/hour per IP for
signup. Tunable via RATE_LIMIT_* env vars.
"
```

- [ ] **Step 1.15: Deploy and smoke-test**

```bash
./deploy/deploy.sh
```

Then verify by signing up a test user and making 51 mission requests:

```bash
ssh root@89.167.39.152 "bash -s" <<'EOF'
docker run --rm --network dispatchzero_default curlimages/curl:latest sh -c '
set -e
CALLSIGN="RateLimitProbe$(date +%s)"
curl -s -c /tmp/c -b /tmp/c -X POST http://app:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d "{\"callsign\":\"$CALLSIGN\",\"password\":\"long-enough-password\",\"adventure_style\":\"agency\"}" > /dev/null
echo "Signed up $CALLSIGN"
# Make 50 requests (should succeed, but they will all hit the wikipedia tier in this remote test which has no real coords)
for i in $(seq 1 51); do
  CODE=$(curl -s -c /tmp/c -b /tmp/c -X POST http://app:8000/missions/request \
    -H "Content-Type: application/json" \
    -d "{\"lat\":47.6605,\"lng\":-117.4198,\"radius_m\":2000}" \
    -o /dev/null -w "%{http_code}")
  echo "request $i: $CODE"
  if [ "$CODE" = "429" ]; then
    echo "Rate limit triggered at request $i — done."
    break
  fi
done
'
EOF
```

Expected: ~50 successful (200) requests, then 429 on the cap. If you see 429 way before 50, check the test cap env var leaked.

Then clean up the test user via psql.

---

## Task 2: Backup pipeline (pg_dump + photos → B2)

**Files:**
- Create: `ops/backup/Dockerfile`
- Create: `ops/backup/entrypoint.sh`
- Create: `ops/backup/nightly-backup.sh`
- Create: `ops/backup/rclone.conf.example`
- Modify: `docker-compose.prod.yml`
- Modify: `.gitignore` (add `ops/backup/rclone.conf`)
- Modify: `.env.example`

### Background

A small alpine sidecar runs `crond` in the foreground. The cron entry fires `nightly-backup.sh` at 03:00 UTC. The script:
1. `pg_dump` the database → `/backups/postgres/dz-YYYY-MM-DD.sql.gz`
2. Rotate local copies — keep last 7 days
3. `rclone copy` the new dump file + the photos directory to B2
4. On B2, retention is handled via lifecycle rules (configured once during setup)

The B2 credentials live in a real `rclone.conf` file mounted from the host (NOT committed). Bucket name + B2 keys come from env vars.

This task assumes B2 is already set up. If not, the operator runbook (`ops/README.md`) documents the steps:
- Create a Backblaze account
- Create a private bucket named `dispatchzero-backups`
- Create an Application Key scoped to that bucket
- On the VPS, install rclone (or use the sidecar's), run `rclone config` once with the keys to produce `~/dispatchzero-rclone.conf`
- Set the lifecycle rule: keep all versions for 30 days, delete after.

- [ ] **Step 2.1: One-time B2 setup (manual, on operator workstation)**

Document this in the operator runbook (`ops/README.md`):

```markdown
# Operator runbook

## Backups (Backblaze B2)

1. Sign up at https://www.backblaze.com/b2/sign-up.html
2. Create a private bucket named `dispatchzero-backups`. Region: any.
3. Set lifecycle rule: "Keep prior versions of files for: 30 days, then hide".
4. Create an Application Key:
   - Name: `dispatchzero-vps2`
   - Bucket: `dispatchzero-backups` (only this bucket)
   - Capabilities: read + write
5. Save the keyID and applicationKey.
6. On VPS 2, install rclone locally for one-time config:
   ```
   curl https://rclone.org/install.sh | bash
   rclone config
   ```
   - Choose `n` (new remote), name `b2`
   - Storage type: `b2`
   - Paste keyID and applicationKey
   - Hard delete: false
   - Save and quit
7. Move the resulting config: `cp ~/.config/rclone/rclone.conf /opt/dispatchzero/ops/backup/rclone.conf`
8. Permissions: `chmod 600 /opt/dispatchzero/ops/backup/rclone.conf`
9. The compose backup service mounts this file read-only.
```

- [ ] **Step 2.2: Write the backup script**

Write to `ops/backup/nightly-backup.sh`:

```bash
#!/bin/sh
# Nightly backup: pg_dump + rotate local + push to B2.
# Runs inside the backup sidecar. Triggered by crond.

set -euo pipefail

STAMP="$(date -u +%Y-%m-%d)"
LOCAL_DIR="/backups/postgres"
DUMP="${LOCAL_DIR}/dz-${STAMP}.sql.gz"

mkdir -p "${LOCAL_DIR}"

echo "[$(date -u)] backup start: ${DUMP}"

# Postgres dump
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
  -h db -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  --no-owner --no-privileges \
  | gzip -9 > "${DUMP}"

# Rotate: keep last 7 days locally
find "${LOCAL_DIR}" -name 'dz-*.sql.gz' -mtime +7 -delete

# Push DB dump to B2 (under postgres/)
rclone --config /etc/rclone.conf copy "${DUMP}" "b2:${B2_BUCKET}/postgres/" \
  --b2-hard-delete=false

# Push photo dir incrementally (sync, but with --immutable so we never delete
# files that have been removed locally — protects against accidental rm).
# Note: B2 versioning + lifecycle handles real deletes.
rclone --config /etc/rclone.conf sync "/photos" "b2:${B2_BUCKET}/photos/" \
  --immutable

echo "[$(date -u)] backup ok"
```

Make it executable in the Dockerfile (`chmod +x` is in the COPY step below).

- [ ] **Step 2.3: Write the entrypoint**

Write to `ops/backup/entrypoint.sh`:

```bash
#!/bin/sh
# Install the cron entry from env, then run crond in the foreground.

set -euo pipefail

echo "${BACKUP_CRON_SCHEDULE:-0 3 * * *} /usr/local/bin/nightly-backup.sh >> /var/log/backup.log 2>&1" \
  > /etc/crontabs/root

# Sanity check: confirm rclone config and pg_dump credentials are present
test -r /etc/rclone.conf || { echo "ERROR: /etc/rclone.conf not mounted"; exit 1; }
test -n "${POSTGRES_PASSWORD:-}" || { echo "ERROR: POSTGRES_PASSWORD unset"; exit 1; }
test -n "${B2_BUCKET:-}" || { echo "ERROR: B2_BUCKET unset"; exit 1; }

echo "[$(date -u)] backup sidecar starting; cron schedule: ${BACKUP_CRON_SCHEDULE:-0 3 * * *}"
exec crond -f -l 8
```

- [ ] **Step 2.4: Write the Dockerfile**

Write to `ops/backup/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM alpine:3.20

RUN apk add --no-cache postgresql16-client rclone tini

COPY entrypoint.sh /entrypoint.sh
COPY nightly-backup.sh /usr/local/bin/nightly-backup.sh
RUN chmod +x /entrypoint.sh /usr/local/bin/nightly-backup.sh

# /backups for local dumps, /photos read-only mount of the upload dir,
# /etc/rclone.conf read-only mount of the B2 config.
VOLUME ["/backups"]

ENTRYPOINT ["/sbin/tini", "--", "/entrypoint.sh"]
```

- [ ] **Step 2.5: Write the rclone.conf example**

Write to `ops/backup/rclone.conf.example`:

```
# Generated by `rclone config` on the operator workstation.
# Real config lives at ops/backup/rclone.conf (gitignored).

[b2]
type = b2
account = <YOUR_B2_KEY_ID>
key = <YOUR_B2_APPLICATION_KEY>
hard_delete = false
```

- [ ] **Step 2.6: Add to .gitignore**

Append to `.gitignore`:

```
ops/backup/rclone.conf
```

- [ ] **Step 2.7: Add B2 vars to .env.example**

Append to `.env.example`:

```
# Backups (B2 via rclone)
B2_BUCKET=dispatchzero-backups
BACKUP_CRON_SCHEDULE=0 3 * * *
```

- [ ] **Step 2.8: Add the sidecar to compose.prod**

Modify `docker-compose.prod.yml` — add new service:

```yaml
  backup:
    build: ./ops/backup
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
      B2_BUCKET: ${B2_BUCKET}
      BACKUP_CRON_SCHEDULE: ${BACKUP_CRON_SCHEDULE:-0 3 * * *}
    volumes:
      - backup_data:/backups
      - /opt/dispatchzero/uploads:/photos:ro
      - ./ops/backup/rclone.conf:/etc/rclone.conf:ro
    depends_on:
      db:
        condition: service_healthy
```

And add the volume:

```yaml
volumes:
  caddy_data:
  caddy_config:
  backup_data:
```

- [ ] **Step 2.9: Sync, build, and verify the container starts**

```bash
./deploy/deploy.sh
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml ps backup"
```

Expected: `backup` service `Up` and healthy. Check logs:

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs backup --tail=20"
```

Should show "backup sidecar starting; cron schedule: 0 3 * * *". If you see "ERROR: /etc/rclone.conf not mounted" — you forgot Step 2.1.7 (mount the conf).

- [ ] **Step 2.10: Trigger a one-shot backup to verify the path works**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backup /usr/local/bin/nightly-backup.sh"
```

Expected output:
- "backup start: /backups/postgres/dz-YYYY-MM-DD.sql.gz"
- rclone progress lines
- "backup ok"

Then verify on B2:

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backup rclone --config /etc/rclone.conf ls b2:${B2_BUCKET}/postgres/"
```

Expected: at least one `dz-YYYY-MM-DD.sql.gz` file listed.

- [ ] **Step 2.11: Verify a restore actually works (the most important step)**

A backup you can't restore from is not a backup.

```bash
ssh root@89.167.39.152 "bash -s" <<'EOF'
# Pull the latest backup, restore into a throwaway DB, count rows
LATEST=$(docker compose -f /opt/dispatchzero/docker-compose.yml -f /opt/dispatchzero/docker-compose.prod.yml \
  exec -T backup ls /backups/postgres/ | grep '\.sql\.gz' | sort | tail -1 | tr -d '\r')
echo "Latest dump: $LATEST"

docker compose -f /opt/dispatchzero/docker-compose.yml -f /opt/dispatchzero/docker-compose.prod.yml \
  exec -T db psql -U dispatchzero -d postgres -c "DROP DATABASE IF EXISTS dz_restore_test;"
docker compose -f /opt/dispatchzero/docker-compose.yml -f /opt/dispatchzero/docker-compose.prod.yml \
  exec -T db psql -U dispatchzero -d postgres -c "CREATE DATABASE dz_restore_test;"

docker compose -f /opt/dispatchzero/docker-compose.yml -f /opt/dispatchzero/docker-compose.prod.yml \
  exec -T backup sh -c "gunzip -c /backups/postgres/$LATEST" \
  | docker compose -f /opt/dispatchzero/docker-compose.yml -f /opt/dispatchzero/docker-compose.prod.yml \
    exec -T db psql -U dispatchzero -d dz_restore_test

# Sanity: did rows come through?
docker compose -f /opt/dispatchzero/docker-compose.yml -f /opt/dispatchzero/docker-compose.prod.yml \
  exec -T db psql -U dispatchzero -d dz_restore_test -c "SELECT COUNT(*) FROM users;"

# Clean up
docker compose -f /opt/dispatchzero/docker-compose.yml -f /opt/dispatchzero/docker-compose.prod.yml \
  exec -T db psql -U dispatchzero -d postgres -c "DROP DATABASE dz_restore_test;"
EOF
```

Expected: row count matches whatever your prod users table has. If `psql` errors during the restore, your dump is bad — fix before considering this task done.

- [ ] **Step 2.12: Commit**

```bash
git add ops/backup docker-compose.prod.yml .env.example .gitignore
git commit -m "feat: nightly backup sidecar to B2 (pg_dump + photos via rclone)

Alpine sidecar runs crond in foreground; nightly-backup.sh dumps Postgres
(7-day local rotation), rclones the dump and the photo dir to B2. Real
rclone.conf is gitignored and mounted from the host. B2 lifecycle handles
remote retention (30 days). Restore verified end-to-end before merge.
"
```

Document the `ops/README.md` if not already done — it's the operator's runbook.

---

## Task 3: Sentry FastAPI integration

**Files:**
- Modify: `pyproject.toml` (add `sentry-sdk[fastapi]`)
- Modify: `src/dispatchzero/main.py` (init Sentry on startup if DSN set)
- Modify: `src/dispatchzero/config.py` (add `sentry_dsn: str | None = None`)
- Modify: `.env.example`

### Background

Sentry's free Developer tier (5k errors/month) is plenty for v1 traffic. The Python SDK's FastAPI integration auto-captures unhandled exceptions, request context, and user context if we add a small middleware.

We init only if `SENTRY_DSN` is set. In dev (no DSN) it's a no-op. In prod we set it via env.

- [ ] **Step 3.1: Manual: get a Sentry DSN**

1. Sign up at https://sentry.io/signup/ — free tier
2. Create a new project: type "Python", framework "FastAPI", name `dispatchzero`
3. Copy the DSN (looks like `https://abc123@o12345.ingest.sentry.io/67890`)
4. Add to `/opt/dispatchzero/.env` on VPS 2: `SENTRY_DSN=<your-dsn>`

- [ ] **Step 3.2: Add the dependency**

Modify `pyproject.toml` — add to `dependencies`:

```toml
    "sentry-sdk[fastapi]>=2.16",
```

Then on VPS 2:

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml build app"
```

(uv.lock will need to be updated locally first if you have a clean dev environment — for now, the prod image rebuild is enough since uv resolves on build.)

Actually — `uv.lock` IS pinned, so update it:

```bash
uv lock
```

Commit `uv.lock` alongside the pyproject.toml change.

- [ ] **Step 3.3: Add the setting**

Modify `src/dispatchzero/config.py` — append to the `Settings` class:

```python
    # Error tracking. None = Sentry disabled (dev/local).
    sentry_dsn: str | None = None
    sentry_environment: str = "production"  # rendered in Sentry as the env tag
    sentry_traces_sample_rate: float = 0.0  # tracing off by default; turn up only when needed
```

- [ ] **Step 3.4: Init Sentry on app startup**

Modify `src/dispatchzero/main.py` — add at the top after the imports, before `app = FastAPI(...)`:

```python
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from dispatchzero.config import get_settings

_settings = get_settings()
if _settings.sentry_dsn:
    sentry_sdk.init(
        dsn=_settings.sentry_dsn,
        environment=_settings.sentry_environment,
        traces_sample_rate=_settings.sentry_traces_sample_rate,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        # Don't send PII (request bodies, headers); we ARE allowed to send the user id
        # via custom tags below.
        send_default_pii=False,
    )
```

- [ ] **Step 3.5: Tag the user id on each request when authed**

We want errors grouped per-user so we can ping testers if they hit a unique bug. Add a small middleware in `main.py`, after `app = FastAPI(...)`:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SentryUserContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _settings.sentry_dsn:
            # Look at the session cookie ourselves rather than running auth machinery.
            # If unsigning fails we just don't tag — no behaviour change.
            try:
                from dispatchzero.auth.session import unsign_session_cookie
                cookie_val = request.cookies.get(_settings.session_cookie_name)
                if cookie_val:
                    payload = unsign_session_cookie(cookie_val)
                    user_id = payload.get("user_id")
                    if user_id:
                        sentry_sdk.set_user({"id": str(user_id)})
            except Exception:
                pass
        return await call_next(request)


app.add_middleware(SentryUserContextMiddleware)
```

(Replace `unsign_session_cookie` with whatever the actual auth helper is named in `dispatchzero.auth.session` or `dispatchzero.auth.deps`. Adjust import accordingly.)

- [ ] **Step 3.6: Add a test endpoint to deliberately trigger an error**

Temporary, will be removed after verification. Add to `main.py` (under the existing `/healthz`):

```python
@app.get("/_sentry_test_only", include_in_schema=False)
async def _sentry_test_only() -> dict:
    """Intentionally raises so we can verify Sentry capture. Remove after verifying."""
    raise RuntimeError("sentry verification probe — safe to ignore in dashboard")
```

- [ ] **Step 3.7: .env.example**

Append:

```
# Error tracking
SENTRY_DSN=
SENTRY_ENVIRONMENT=production
```

- [ ] **Step 3.8: Sanity test locally — Sentry NOT configured**

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest tests/ -k healthz"
```

Expected: still passes; without DSN, init is a no-op.

- [ ] **Step 3.9: Deploy and verify the test probe lands in Sentry**

Set the DSN in prod `.env`, then:

```bash
./deploy/deploy.sh
ssh root@89.167.39.152 "docker run --rm --network dispatchzero_default curlimages/curl:latest \
  curl -s http://app:8000/_sentry_test_only -w '\nHTTP %{http_code}\n'"
```

Expected: HTTP 500 (the probe raised). Then check the Sentry dashboard — you should see the `RuntimeError` event within ~30s, tagged `environment: production`.

- [ ] **Step 3.10: Remove the test probe**

Delete `_sentry_test_only` from `main.py`.

- [ ] **Step 3.11: Commit**

```bash
git add pyproject.toml uv.lock src/dispatchzero/main.py src/dispatchzero/config.py .env.example
git commit -m "feat: Sentry FastAPI integration; user-id tag from session cookie

Errors are auto-captured. PII is off (request bodies/headers redacted) but
we attach the user id from the session cookie so we can correlate per-user
crash patterns. No-op when SENTRY_DSN is unset (dev/local).
"
./deploy/deploy.sh
```

---

## Task 4: Log rotation + disk-fill alert

**Files:**
- Modify: `docker-compose.prod.yml` (logging driver options on every service)
- Create: `ops/disk-alert/Dockerfile`
- Create: `ops/disk-alert/entrypoint.sh`
- Create: `ops/disk-alert/check-disk.sh`
- Modify: `.env.example` (add `NTFY_TOPIC`, `DISK_ALERT_THRESHOLD`)

### Background

Two parts:
1. **Log rotation** — Docker's `json-file` log driver, capped at 10 MB × 3 files per service. Without this, a chatty service can fill `/var/lib/docker` indefinitely.
2. **Disk alert** — a small alpine sidecar that wakes every 15 minutes, checks `df` for `/`, and POSTs to a hardcoded ntfy.sh topic if usage exceeds a threshold. ntfy is dead simple: `curl -d "msg" ntfy.sh/<topic>` and you get a phone push (after subscribing).

The ntfy topic is a string the operator chooses. It's a public URL but unguessable if you pick something like `dispatchzero-alerts-x9k3pq2v8z`. Trevor subscribes via the ntfy app on his phone.

- [ ] **Step 4.1: Set log-driver options on every service**

Modify `docker-compose.prod.yml` — add this `logging` block under each service (`app`, `caddy`, `db`, `redis`, `backup`, plus the new `disk-alert` from this task):

```yaml
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

Yaml anchor avoids repetition:

```yaml
x-default-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"

services:
  caddy:
    # ...
    logging: *default-logging
  app:
    logging: *default-logging
  db:
    logging: *default-logging
  redis:
    logging: *default-logging
  backup:
    logging: *default-logging
```

- [ ] **Step 4.2: Pick a ntfy topic**

```bash
python -c "import secrets; print(f'dispatchzero-alerts-{secrets.token_urlsafe(8).lower()}')"
```

Save the output. Add to `/opt/dispatchzero/.env`:

```
NTFY_TOPIC=dispatchzero-alerts-<the-suffix-you-generated>
DISK_ALERT_THRESHOLD=85
```

Subscribe on your phone:
- Install ntfy from App Store / Play Store
- Add subscription: `https://ntfy.sh/<your-topic>`
- Keep notifications enabled

- [ ] **Step 4.3: Write the disk-check script**

Write to `ops/disk-alert/check-disk.sh`:

```bash
#!/bin/sh
set -eu

USAGE=$(df -P / | awk 'NR==2 {sub("%",""); print $5}')
THRESHOLD="${DISK_ALERT_THRESHOLD:-85}"
TOPIC="${NTFY_TOPIC:?NTFY_TOPIC unset}"

if [ "${USAGE}" -ge "${THRESHOLD}" ]; then
  HOST="$(cat /etc/hostname || echo unknown)"
  curl -s -d "Disk on ${HOST} at ${USAGE}% (threshold ${THRESHOLD}%). df / output:
$(df -h /)" \
    -H "Title: Dispatch Zero — disk fill warning" \
    -H "Priority: high" \
    -H "Tags: warning,floppy_disk" \
    "https://ntfy.sh/${TOPIC}"
  echo "[$(date -u)] alert sent: usage ${USAGE}%"
else
  echo "[$(date -u)] ok: usage ${USAGE}%"
fi
```

- [ ] **Step 4.4: Write the entrypoint and Dockerfile**

Write to `ops/disk-alert/entrypoint.sh`:

```bash
#!/bin/sh
set -euo pipefail

# Run every 15 min. The sidecar mounts the HOST root at /host so we can read
# its disk usage rather than the container's.
echo "*/15 * * * * /usr/local/bin/check-disk.sh >> /var/log/disk-alert.log 2>&1" \
  > /etc/crontabs/root

test -n "${NTFY_TOPIC:-}" || { echo "ERROR: NTFY_TOPIC unset"; exit 1; }

echo "[$(date -u)] disk-alert starting; threshold=${DISK_ALERT_THRESHOLD:-85}%"
exec crond -f -l 8
```

Write to `ops/disk-alert/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM alpine:3.20

RUN apk add --no-cache curl tini

COPY entrypoint.sh /entrypoint.sh
COPY check-disk.sh /usr/local/bin/check-disk.sh
RUN chmod +x /entrypoint.sh /usr/local/bin/check-disk.sh

ENTRYPOINT ["/sbin/tini", "--", "/entrypoint.sh"]
```

- [ ] **Step 4.5: Add the sidecar to compose.prod**

In `docker-compose.prod.yml`:

```yaml
  disk-alert:
    build: ./ops/disk-alert
    restart: unless-stopped
    environment:
      NTFY_TOPIC: ${NTFY_TOPIC}
      DISK_ALERT_THRESHOLD: ${DISK_ALERT_THRESHOLD:-85}
    # The container's / is its own; we want the host's disk usage.
    # Mount host root as / via privileged + propagated mount? simpler:
    # mount host root as a sub-path and have the script df THAT.
    volumes:
      - /:/host:ro
    logging: *default-logging
```

Then the script needs to df the host mount. Update `check-disk.sh`:

```bash
USAGE=$(df -P /host | awk 'NR==2 {sub("%",""); print $5}')
```

(replace the existing `df -P /` line)

- [ ] **Step 4.6: Add to .env.example**

Append to `.env.example`:

```
# Disk alert (ntfy.sh)
NTFY_TOPIC=dispatchzero-alerts-changeme
DISK_ALERT_THRESHOLD=85
```

- [ ] **Step 4.7: Deploy and force a test alert**

```bash
./deploy/deploy.sh
```

Verify the service is up:

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml ps disk-alert"
```

Force an alert by setting threshold to 1 temporarily:

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && DISK_ALERT_THRESHOLD=1 docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -e DISK_ALERT_THRESHOLD=1 disk-alert /usr/local/bin/check-disk.sh"
```

Expected: phone push notification within seconds. If you get nothing, check:
- Is your ntfy subscription on the right topic?
- Did the curl succeed? (run `docker compose ... logs disk-alert` for the response)

- [ ] **Step 4.8: Verify log rotation took effect**

```bash
ssh root@89.167.39.152 "docker inspect dispatchzero-app-1 --format '{{json .HostConfig.LogConfig}}'"
```

Expected: `{"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}`

- [ ] **Step 4.9: Commit**

```bash
git add docker-compose.prod.yml ops/disk-alert .env.example
git commit -m "feat: log rotation (10m × 3) + disk-fill ntfy alert sidecar

Docker json-file driver capped per service. New disk-alert sidecar checks
host disk every 15 min and POSTs to ntfy.sh when /  > threshold (default
85%). Operator subscribes to ntfy topic on phone via the ntfy app.
"
```

---

## Task 5: External uptime monitoring (manual, no code)

**Files:** none (configuration is in UptimeRobot's web UI, documented in `ops/README.md`).

- [ ] **Step 5.1: Sign up for UptimeRobot**

https://uptimerobot.com/ — free tier, 50 monitors, 5-minute interval.

- [ ] **Step 5.2: Add a monitor**

- Type: HTTP(s)
- URL: `https://dispatchzero.johnsonfarms.us/healthz`
- Interval: 5 minutes
- Friendly name: `Dispatch Zero`
- Alert contacts: your email; optionally also the same ntfy topic via "Webhook" alert contact (URL: `https://ntfy.sh/<your-topic>`, method POST, payload: `Dispatch Zero is *alertTypeFriendlyName*`)

- [ ] **Step 5.3: Verify by simulating an outage**

Stop the app for ~6 minutes:

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml stop app"
sleep 360
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.prod.yml start app"
```

Expected: UptimeRobot emails you and (if you wired the webhook) pushes to ntfy. Check the dashboard — incident should be logged.

- [ ] **Step 5.4: Add to runbook**

Append to `ops/README.md`:

```markdown
## Uptime monitoring (UptimeRobot)

External 5-min HTTP probe against /healthz. Monitor name: "Dispatch Zero".
Alerts go to <your-email> and to the ntfy topic. To pause during planned
maintenance: dashboard → monitor → Pause.
```

- [ ] **Step 5.5: Commit the README update**

```bash
git add ops/README.md
git commit -m "docs: document UptimeRobot setup in ops runbook"
```

---

## Task 6: Beta banner

**Files:**
- Modify: `src/dispatchzero/config.py` (add `show_beta_banner: bool = False`)
- Modify: `src/dispatchzero/main.py` (add `GET /config` returning a small public config dict)
- Create: `tests/test_config_endpoint.py`
- Modify: `frontend/static/js/screens/splash.js`
- Modify: `frontend/static/js/screens/home.js`
- Modify: `frontend/static/js/api.js` (or add a one-off fetch helper)
- Modify: `.env.example`

### Background

A small "BETA — closed pilot" badge on Splash + Home, controlled by an env var. Set `SHOW_BETA_BANNER=true` for now; flip to false when going public. The frontend learns about it via a minimal `GET /config` endpoint (publicly accessible, no auth) returning `{"show_beta_banner": true}`.

- [ ] **Step 6.1: Setting + endpoint**

Modify `src/dispatchzero/config.py`:

```python
    show_beta_banner: bool = False
```

Modify `src/dispatchzero/main.py` — add:

```python
@app.get("/config")
async def public_config() -> dict:
    """Public, unauthenticated config the frontend may need to render."""
    s = get_settings()
    return {
        "show_beta_banner": s.show_beta_banner,
    }
```

- [ ] **Step 6.2: Test the endpoint**

Write to `tests/test_config_endpoint.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_config_endpoint_reflects_banner_setting(client, monkeypatch):
    monkeypatch.setenv("SHOW_BETA_BANNER", "true")
    r = await client.get("/config")
    assert r.status_code == 200
    assert r.json()["show_beta_banner"] is True

    monkeypatch.setenv("SHOW_BETA_BANNER", "false")
    r = await client.get("/config")
    assert r.json()["show_beta_banner"] is False
```

Run it:

```bash
ssh root@89.167.39.152 "cd /opt/dispatchzero && docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test pytest tests/test_config_endpoint.py -v"
```

Expected: 1 passed.

- [ ] **Step 6.3: Frontend — fetch and render**

Modify `frontend/static/js/screens/splash.js` (and similarly `home.js`):

At the top of the function, add:

```js
let showBanner = false;
try {
  const r = await api.get("/config");
  if (r.ok) showBanner = !!r.data.show_beta_banner;
} catch { /* ignore */ }
```

In the returned element tree, add a banner row (only if `showBanner`):

```js
  // Inside the "screen" container, top of "content":
  ...(showBanner ? [
    el("div", {
      class: "row",
      style: {
        backgroundColor: "var(--surface-warn, #3a2a0a)",
        color: "var(--text-warn, #f4d35e)",
        padding: "var(--s-1)",
        textAlign: "center",
        fontFamily: "var(--font-mono)",
        fontSize: "var(--t-xs)",
        letterSpacing: "0.05em",
      },
    }, "// BETA — closed pilot //")
  ] : []),
```

- [ ] **Step 6.4: .env.example**

Append:

```
# Show the BETA banner on Splash + Home (flip to false for public launch)
SHOW_BETA_BANNER=true
```

- [ ] **Step 6.5: Set env on prod**

```bash
ssh root@89.167.39.152 "echo 'SHOW_BETA_BANNER=true' >> /opt/dispatchzero/.env"
```

- [ ] **Step 6.6: Deploy and verify on phone**

```bash
./deploy/deploy.sh
```

Hard-refresh on phone, look for the banner on Splash + Home.

- [ ] **Step 6.7: Commit**

```bash
git add src/dispatchzero/config.py src/dispatchzero/main.py tests/test_config_endpoint.py \
        frontend/static/js/screens/splash.js frontend/static/js/screens/home.js .env.example
git commit -m "feat: env-toggled BETA banner on Splash + Home

Backend exposes show_beta_banner via /config (public, unauthenticated). Flip
SHOW_BETA_BANNER=false on .env to remove it for public launch.
"
```

---

## Phase 14 — Definition of Done

All of the following must be true:

- [ ] **Rate limits live in prod.** A user account can be made to hit 429 on `/missions/request` after the configured cap. Confirmed via the smoke script in Step 1.15.
- [ ] **Backups verified end-to-end.** `nightly-backup.sh` produces a dump locally AND in B2; the dump can be restored to a throwaway DB and `SELECT COUNT(*) FROM users` returns the live row count. Step 2.11 documents the procedure — if you didn't run it, the task isn't done.
- [ ] **Sentry has captured at least one real error.** The verification probe from Step 3.9 appears in the Sentry dashboard tagged `environment: production`. The probe is then removed.
- [ ] **Log rotation is enforced.** `docker inspect` confirms the log config on at least three services.
- [ ] **Disk alert fires.** A forced low-threshold run pushes a notification to your phone.
- [ ] **UptimeRobot is running.** Manual outage simulation triggered an alert email AND a ntfy push (if webhook wired). Monitor is back to green.
- [ ] **Beta banner renders.** Visible on Splash + Home; flipping `SHOW_BETA_BANNER=false` and redeploying removes it (verify the toggle works before launch day).
- [ ] **Operator runbook (`ops/README.md`) is complete.** Anyone with sudo on VPS 2 can follow it to reproduce or audit the entire hardening setup. Includes B2 setup, rclone config location, Sentry DSN location, ntfy topic + how to subscribe, UptimeRobot dashboard URL.

---

## Open decisions held for later (not blocking Phase 14)

| Decision | Defer until | Notes |
|---|---|---|
| Cloudflare in front of Caddy | Tester pool > 50, OR a leak triggers DDoS | Free tier covers it; adds one DNS layer |
| Per-IP request rate limits beyond signup | First time we see abuse logs | Current per-user limits cover the cost surface |
| 2FA / passkey auth | Not v1 — the spec is callsign+password | Maybe Phase 16+ |
| Dedicated backup VM | If VPS 2 ever fills above 50% | One-host setup is fine until growth |
| Glitchtip self-host | If Sentry's 5k/month is exceeded | Unlikely at v1 traffic |
| Redis persistence (AOF) | When we start storing meaningful state in Redis | Currently Redis is just cache + rate-limit counters; data loss on restart is acceptable |
| Photo storage off-host (e.g., B2 directly) | When local disk pressure becomes real | Backups already cover the durability concern |

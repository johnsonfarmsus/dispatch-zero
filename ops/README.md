# dispatch-zero — operator runbook

Post-deploy steps + manual operations. Product spec is in
`../dispatch-zero_project_document.md`; phase plans are in
`../docs/plans/`.

---

## Rate limits

Tunable via env vars in `/opt/dispatchzero/.env` (defaults are sane —
override only if you see legitimate caps biting):

```
RATE_LIMIT_MISSION_REQUEST_PER_DAY=50
RATE_LIMIT_MISSION_GENERATE_PER_DAY=50
RATE_LIMIT_SIGNUP_PER_IP_PER_HOUR=10
```

After changing, recreate `app`:

```bash
ssh root@89.167.39.152 \
  "cd /opt/dispatchzero \
   && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d app"
```

---

## Log rotation

Every prod service (caddy, app, db, redis) has the json-file driver
capped at 10 MB × 3 files via the `x-default-logging` anchor in
`docker-compose.prod.yml`. Verify on a running container:

```bash
ssh root@89.167.39.152 \
  "docker inspect dispatchzero-app-1 --format '{{json .HostConfig.LogConfig}}'"
# expected: {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
```

---

## Watching for problems (manual, no alerting shipped)

Phase 14 deliberately does NOT include a push-alert system. To check
on prod by hand:

**Recent app errors:**
```bash
ssh root@89.167.39.152 \
  "cd /opt/dispatchzero \
   && docker compose -f docker-compose.yml -f docker-compose.prod.yml \
        logs app --since 24h | grep -iE 'error|traceback' | tail -50"
```

**Disk pressure:**
```bash
ssh root@89.167.39.152 "df -h /"
```

**Container state:**
```bash
ssh root@89.167.39.152 \
  "cd /opt/dispatchzero \
   && docker compose -f docker-compose.yml -f docker-compose.prod.yml ps"
```

If/when this becomes too manual, options for keeping things in-house:

- Self-hosted **ntfy** (single Go binary, run `ntfy serve` on VPS 3
  next to Mailcow) — same protocol, same phone app, your own server
- Self-hosted **GlitchTip** or **Bugsink** for error tracking with a
  dashboard, both Sentry-API compatible
- A small cron + email script using your existing Mailcow on VPS 3
- A cron on VPS 3 that hits `https://dispatchzero.../healthz` and
  emails you on failure

Pick when the scale demands it; not before.

---

## What's NOT shipped (intentional)

- **Off-host backups** — Hetzner already takes VPS-level snapshots
- **External uptime monitoring** — word-of-mouth at MVP scale
- **Error tracking SaaS / push alerts** — see "Watching for problems" above

See `docs/plans/2026-04-27-phase-14-launch-hardening.md` for the
context on each.

# dispatch-zero operator runbook

Post-deploy steps + manual operations. Product spec is in
`../dispatch-zero_project_document.md`; phase plans are in
`../docs/plans/`.

---

## Rate limits

Tunable via env vars in `/opt/dispatchzero/.env`. Defaults are sane;
override only if you see legitimate caps biting:

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

## Health checks

Two endpoints:

- `GET /healthz` — shallow liveness (the process is up). Used by the
  deploy script's post-start check.
- `GET /healthz/deep` — readiness: pings Postgres + Redis with short
  timeouts. Returns 503 with a per-component breakdown if any hard
  dependency is down. (Ollama is intentionally NOT pinged — a cold model
  would flap the check and the app degrades gracefully when it's slow.)

A 5-line cron can turn `/healthz/deep` into alerting via the existing
Mailcow on VPS 3:

```bash
# crontab on VPS 3
*/5 * * * * curl -fsS https://dispatchzero.ataary.com/healthz/deep > /dev/null \
  || echo "Dispatch Zero deep healthcheck FAILED at $(date -u)" \
     | mail -s "DZ health alert" trevor@johnsonfarms.us
```

## Backups

`deploy/backup.sh` writes a `pg_dump` (custom format, restorable with
`pg_restore`) + an `uploads/` tarball to `/opt/dispatchzero-backups`,
keeping the last 14 sets. This complements Hetzner's whole-VM snapshots
(which don't protect against a bad migration or a logical DELETE) and
stays fully in-house.

```bash
# crontab on VPS 2
0 3 * * * /opt/dispatchzero/deploy/backup.sh >> /var/log/dz-backup.log 2>&1
```

Restore (manual; see the script footer for exact commands):
- DB: `pg_restore -U <user> -d <db> --clean < db-<stamp>.dump`
- uploads: `tar -xzf uploads-<stamp>.tar.gz -C /opt/dispatchzero`

## Watching for problems (log-only watchdog, no push alerts)

A cron watchdog runs on the VPS every 5 minutes and writes **state
transitions only** to `/var/log/dz-watchdog.log`:

- `GET /healthz/deep` (Postgres + Redis pings inside the app)
- root-filesystem usage vs an 85% threshold (`DZ_DISK_THRESHOLD` to tune)
- `docker compose ps` — any non-running service

Healthy runs log at most one `HEARTBEAT` line per day, so the log stays
readable for months and silence is distinguishable from a dead cron.

```bash
ssh root@89.167.39.152 "tail -20 /var/log/dz-watchdog.log"   # recent state
ssh root@89.167.39.152 "grep DOWN /var/log/dz-watchdog.log"  # outage windows
```

Install (idempotent — safe to re-run):
```bash
ssh root@89.167.39.152 \
  "chmod +x /opt/dispatchzero/deploy/watchdog.sh && \
   (crontab -l 2>/dev/null | grep -q watchdog.sh || \
    (crontab -l 2>/dev/null; echo '*/5 * * * * /opt/dispatchzero/deploy/watchdog.sh') | crontab -)"
```

There is deliberately no push alerting — checking the log is a pull.
To check deeper by hand:

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

If/when log-only becomes too manual, options for keeping things in-house:

- Self-hosted **ntfy** (single Go binary) on one of the VPSes. Same
  protocol as the SaaS, same phone app, your own server
- Self-hosted **GlitchTip** or **Bugsink** for error tracking with a
  dashboard, both Sentry-API compatible

(Note: VPS 3 no longer runs a mail server, so the earlier cron+email
ideas would need an SMTP relay that doesn't currently exist.)

Pick when the scale demands it; not before.

---

## What's NOT shipped (intentional)

- **Off-host backups.** Hetzner already takes VPS-level snapshots
- **External uptime monitoring.** Word-of-mouth at MVP scale
- **Error tracking SaaS / push alerts.** See "Watching for problems" above

See `docs/plans/2026-04-27-phase-14-launch-hardening.md` for the
context on each.

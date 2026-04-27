# dispatch-zero — operator runbook

Post-deploy checklist + manual steps. Lives next to the sidecars
they apply to. The product spec is in
`../dispatch-zero_project_document.md`; phase plans are in
`../docs/plans/`.

---

## Post-deploy checklist (Phase 14)

After a deploy that brings up the rate-limit / ntfy-alert / banner stack
for the first time, do these once.

### 1. Pick an unguessable ntfy topic

ntfy.sh topics are public — anyone with the topic name can publish or
subscribe. Use enough entropy that it's effectively unguessable.

```bash
python3 -c "import secrets; print(f'dz-alerts-{secrets.token_urlsafe(8).lower()}')"
# example output: dz-alerts-xq7r2k9mwf
```

### 2. Set the topic on the VPS

```bash
ssh root@89.167.39.152
echo 'NTFY_TOPIC=dz-alerts-xq7r2k9mwf' >> /opt/dispatchzero/.env  # use your topic
chmod 600 /opt/dispatchzero/.env
exit
```

### 3. Recreate the affected containers so they pick up the new env

```bash
ssh root@89.167.39.152 \
  "cd /opt/dispatchzero \
   && docker compose -f docker-compose.yml -f docker-compose.prod.yml \
        up -d disk-alert app"
```

The `app` container reinstalls the `NtfyAlertHandler` at startup; the
`disk-alert` sidecar exits its idle path and starts the 15-minute cron.

### 4. Subscribe on phone

- Install the **ntfy** app (App Store / Play Store)
- Add subscription: `https://ntfy.sh/<your-topic>`
- Allow notifications

### 5. Verify both alert paths

**Disk alert (force a test push):**

```bash
ssh root@89.167.39.152 \
  "cd /opt/dispatchzero \
   && docker compose -f docker-compose.yml -f docker-compose.prod.yml \
        exec disk-alert env DISK_ALERT_THRESHOLD=1 /usr/local/bin/check-disk.sh"
```

You should get a phone push within seconds: `"Dispatch Zero - disk fill warning"`.

**App error alert (verify on next real exception):**
There's no probe endpoint shipped — the next genuine unhandled
exception in prod will push automatically. To trigger one synthetically
without leaving a probe in the codebase:

```bash
ssh root@89.167.39.152 \
  "cd /opt/dispatchzero \
   && docker compose -f docker-compose.yml -f docker-compose.prod.yml \
        exec app python -c \
        'import logging; logging.error(\"smoke-test from operator runbook\")'"
```

A push should arrive titled `"Dispatch Zero - application error"`.

---

## Beta banner

The home / splash screens show a `// BETA — closed pilot //` bar by
default. Flip it off for public launch:

```bash
# In /opt/dispatchzero/.env on VPS 2:
SHOW_BETA_BANNER=false
```

Then recreate `app`:

```bash
ssh root@89.167.39.152 \
  "cd /opt/dispatchzero \
   && docker compose -f docker-compose.yml -f docker-compose.prod.yml \
        up -d app"
```

Hard-refresh the PWA on phone to bypass the service worker.

---

## Sidecars

### `disk-alert/`

- Alpine container with `crond` running the `check-disk.sh` script
  every 15 minutes.
- Watches the host root via the read-only `/host` bind mount.
- Posts to ntfy.sh when disk usage exceeds `DISK_ALERT_THRESHOLD`
  (default 85%).
- Idles harmlessly via `tail -f /dev/null` when `NTFY_TOPIC` is unset
  — no crash loop with `restart: unless-stopped`.

Tail the cron output to confirm it's alive:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  logs disk-alert --tail=20
```

You should see `[<timestamp>] ok: usage NN% (threshold 85%)` lines
every 15 min.

---

## Things deliberately NOT shipped (so you know not to look for them)

- **Off-host backups** — Hetzner's VPS snapshots cover every realistic
  recovery scenario for this MVP. Manual `pg_dump` is one command away
  if a specific incident calls for a logical dump.
- **External uptime monitoring** — at small tester-pool scale,
  word-of-mouth is sufficient. When this comes back, prefer
  cron + curl + ntfy on VPS 3 (Mailcow box) over UptimeRobot to stay
  on Trevor's own infrastructure.
- **Sentry / GlitchTip / Bugsink** — Phase 14's error tracking is the
  in-process `NtfyAlertHandler`. Migration path to self-hosted Bugsink
  remains open if push-on-error becomes noise: Bugsink is Sentry-API
  compatible, so the migration is "deploy Bugsink, set
  `SENTRY_DSN=http://bugsink.local/...`, add the `sentry-sdk[fastapi]`
  init in `main.py`."

See `docs/plans/2026-04-27-phase-14-launch-hardening.md` for the full
context on each of these.

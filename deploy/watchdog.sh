#!/usr/bin/env bash
# Log-only watchdog for Dispatch Zero. Runs on the VPS host via cron:
#
#   */5 * * * * /opt/dispatchzero/deploy/watchdog.sh
#
# Design: NO push alerts by choice (in-house only, no SaaS, no mail).
# The value is a durable, greppable record of state TRANSITIONS — when the
# stack went unhealthy, what exactly failed (per-service healthz detail,
# disk %, container states), and when it recovered. Healthy runs write at
# most one heartbeat line per day, so the log stays readable for months.
#
#   tail -20 /var/log/dz-watchdog.log        # recent state changes
#   grep DOWN /var/log/dz-watchdog.log       # every outage window
#
# Checks:
#   1. GET /healthz/deep on the app (pings Postgres + Redis internally)
#   2. Root filesystem usage vs threshold (the Paperclip /tmp leak filled
#      the disk once already — catching the climb beats explaining MISCONF)
#   3. docker compose services all running
set -u

LOG_FILE="${DZ_WATCHDOG_LOG:-/var/log/dz-watchdog.log}"
STATE_FILE="${DZ_WATCHDOG_STATE:-/var/lib/dz-watchdog.state}"
# Public URL on purpose: in prod the app container has no host port
# (ports: !reset [] — Caddy reaches it on the compose network), and going
# through Caddy makes this an end-to-end check of TLS + proxy + app + deps.
APP_URL="${DZ_WATCHDOG_URL:-https://dispatchzero.ataary.com/healthz/deep}"
COMPOSE_DIR="${DZ_COMPOSE_DIR:-/opt/dispatchzero}"
DISK_THRESHOLD="${DZ_DISK_THRESHOLD:-85}"

ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
log() { echo "$(ts) $*" >> "$LOG_FILE"; }

# --- 1. deep health ---------------------------------------------------------
health_body="$(curl -sS -m 10 "$APP_URL" 2>&1)"
health_code=$?
if [ $health_code -ne 0 ]; then
    health="DOWN"
    health_detail="healthz unreachable: ${health_body:0:200}"
elif echo "$health_body" | grep -q '"status": *"ok"'; then
    health="OK"
    health_detail=""
else
    health="DEGRADED"
    health_detail="healthz body: ${health_body:0:200}"
fi

# --- 2. disk ----------------------------------------------------------------
disk_pct="$(df --output=pcent / 2>/dev/null | tail -1 | tr -dc '0-9')"
disk_state="OK"
if [ -n "$disk_pct" ] && [ "$disk_pct" -ge "$DISK_THRESHOLD" ]; then
    disk_state="FULL"
fi

# --- 3. containers ----------------------------------------------------------
containers_down=""
if command -v docker >/dev/null 2>&1 && [ -d "$COMPOSE_DIR" ]; then
    containers_down="$(cd "$COMPOSE_DIR" && \
        docker compose -f docker-compose.yml -f docker-compose.prod.yml ps \
            --format '{{.Service}}={{.State}}' 2>/dev/null | \
        grep -v '=running' | tr '\n' ' ')"
fi
container_state="OK"
[ -n "$containers_down" ] && container_state="DOWN"

# --- state transition logging ----------------------------------------------
current="health=${health} disk=${disk_state}:${disk_pct:-?}% containers=${container_state}"
# Disk % changes constantly; the STATE key must only track category flips,
# not every percentage tick, or the log fills with noise.
current_key="health=${health} disk=${disk_state} containers=${container_state}"

previous_key=""
[ -f "$STATE_FILE" ] && previous_key="$(cat "$STATE_FILE")"

if [ "$current_key" != "$previous_key" ]; then
    log "TRANSITION ${previous_key:-<first run>} -> ${current}"
    [ -n "$health_detail" ] && log "  detail: ${health_detail}"
    [ -n "$containers_down" ] && log "  containers: ${containers_down}"
    printf '%s' "$current_key" > "$STATE_FILE"
else
    # Healthy heartbeat at most once a day so silence is distinguishable
    # from a dead cron.
    last_line_day="$(tail -1 "$LOG_FILE" 2>/dev/null | cut -c1-10)"
    [ "$last_line_day" != "$(date -u '+%Y-%m-%d')" ] && log "HEARTBEAT ${current}"
fi

exit 0

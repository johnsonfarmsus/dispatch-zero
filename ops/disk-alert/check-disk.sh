#!/bin/sh
# Check host root disk usage; POST to ntfy.sh if above threshold.
# Designed to be invoked by crond inside the disk-alert sidecar.
set -eu

# /host is the read-only host root mount (see compose).
USAGE=$(df -P /host | awk 'NR==2 {sub("%",""); print $5}')
# Default matches docker-compose.prod.yml; keep them in sync if changed.
THRESHOLD="${DISK_ALERT_THRESHOLD:-85}"

# Allow manual invocation without NTFY_TOPIC (for ad-hoc threshold testing
# from the host). Print a clear message and exit cleanly.
TOPIC="${NTFY_TOPIC:-}"
if [ -z "${TOPIC}" ]; then
  echo "[$(date -u)] NTFY_TOPIC unset — usage ${USAGE}% (threshold ${THRESHOLD}%); not sending."
  exit 0
fi

if [ "${USAGE}" -ge "${THRESHOLD}" ]; then
  HOST="$(cat /etc/host_hostname 2>/dev/null || echo dispatchzero-vps)"
  BODY="Disk on ${HOST} at ${USAGE}% (threshold ${THRESHOLD}%).
$(df -h /host)"
  # --max-time 10: ntfy is fire-and-forget, never block a cron slot for
  # more than ~10s if the network is sad.
  curl -s --max-time 10 \
    -H "Title: Dispatch Zero - disk fill warning" \
    -H "Priority: high" \
    -H "Tags: warning,floppy_disk" \
    -d "${BODY}" \
    "https://ntfy.sh/${TOPIC}" || true
  echo "[$(date -u)] alert sent: usage ${USAGE}% (threshold ${THRESHOLD}%)"
else
  echo "[$(date -u)] ok: usage ${USAGE}% (threshold ${THRESHOLD}%)"
fi

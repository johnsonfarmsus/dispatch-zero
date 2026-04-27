#!/bin/sh
# Check host root disk usage; POST to ntfy.sh if above threshold.
# Designed to be invoked by crond inside the disk-alert sidecar.
set -eu

# /host is the read-only host root mount (see compose).
USAGE=$(df -P /host | awk 'NR==2 {sub("%",""); print $5}')
THRESHOLD="${DISK_ALERT_THRESHOLD:-85}"
TOPIC="${NTFY_TOPIC:?NTFY_TOPIC unset}"

if [ "${USAGE}" -ge "${THRESHOLD}" ]; then
  HOST="$(cat /etc/host_hostname 2>/dev/null || echo dispatchzero-vps)"
  BODY="Disk on ${HOST} at ${USAGE}% (threshold ${THRESHOLD}%).
$(df -h /host)"
  curl -s \
    -H "Title: Dispatch Zero - disk fill warning" \
    -H "Priority: high" \
    -H "Tags: warning,floppy_disk" \
    -d "${BODY}" \
    "https://ntfy.sh/${TOPIC}" || true
  echo "[$(date -u)] alert sent: usage ${USAGE}% (threshold ${THRESHOLD}%)"
else
  echo "[$(date -u)] ok: usage ${USAGE}% (threshold ${THRESHOLD}%)"
fi

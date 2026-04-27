#!/bin/sh
# Install the cron entry, then exec crond in the foreground.
set -eu

# Graceful no-op if no NTFY_TOPIC is configured. Stack stays up; alert is
# just disabled. Prefer this to exit 1 because exit 1 plus restart:unless-stopped
# means an infinite restart loop.
if [ -z "${NTFY_TOPIC:-}" ]; then
  echo "[$(date -u)] NTFY_TOPIC unset — disk-alert disabled. Idling."
  exec tail -f /dev/null
fi

# Run check every 15 min. Quiet output goes to stdout so docker logs picks it up.
echo "*/15 * * * * /usr/local/bin/check-disk.sh >> /proc/1/fd/1 2>&1" \
  > /etc/crontabs/root

echo "[$(date -u)] disk-alert starting; threshold=${DISK_ALERT_THRESHOLD:-85}% topic=${NTFY_TOPIC}"
exec crond -f -l 8

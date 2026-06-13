#!/usr/bin/env bash
# In-house nightly backup: pg_dump + uploads tarball to a second location on
# the same VPS. Complements (does NOT replace) Hetzner's whole-VM snapshots:
# snapshots are coarse and don't protect against a bad migration, a logical
# DELETE, or a corrupted row. This gives a portable, restorable point-in-time
# copy you can diff, inspect, and pull off-box.
#
# Stays fully in-house (no external SaaS) per the project's constraints.
#
# Run on the VPS, e.g. via cron:
#   0 3 * * *  /opt/dispatchzero/deploy/backup.sh >> /var/log/dz-backup.log 2>&1
#
# Configure via env (or the .env the compose stack already uses):
#   DZ_REMOTE_DIR    app dir on the VPS         (default /opt/dispatchzero)
#   DZ_BACKUP_DIR    where backups are written  (default /opt/dispatchzero-backups)
#   DZ_BACKUP_KEEP   how many daily sets to keep (default 14)
set -euo pipefail

REMOTE_DIR="${DZ_REMOTE_DIR:-/opt/dispatchzero}"
BACKUP_DIR="${DZ_BACKUP_DIR:-/opt/dispatchzero-backups}"
KEEP="${DZ_BACKUP_KEEP:-14}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
COMPOSE="docker compose -f ${REMOTE_DIR}/docker-compose.yml -f ${REMOTE_DIR}/docker-compose.prod.yml"

mkdir -p "${BACKUP_DIR}"

# Pull POSTGRES_* from the stack's .env so we don't duplicate credentials.
# shellcheck disable=SC1091
set -a; source "${REMOTE_DIR}/.env"; set +a

echo "[backup ${STAMP}] pg_dump"
# Custom format (-Fc) is compressed + restorable with pg_restore. Exec inside
# the db container so we use the in-network socket and the stack's creds.
${COMPOSE} exec -T db \
  pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -Fc \
  > "${BACKUP_DIR}/db-${STAMP}.dump"

echo "[backup ${STAMP}] uploads tarball"
# uploads/ holds user photos + composed cards — the irreplaceable runtime
# data (already protected from the deploy-rsync wipe by its uploads exclude;
# this is the independent off-rsync copy). Skip if the dir doesn't exist yet.
if [[ -d "${REMOTE_DIR}/uploads" ]]; then
  tar -czf "${BACKUP_DIR}/uploads-${STAMP}.tar.gz" -C "${REMOTE_DIR}" uploads
else
  echo "  (no uploads/ dir yet; skipping)"
fi

echo "[backup ${STAMP}] pruning older than ${KEEP} sets"
# Keep the most recent KEEP of each artifact; delete the rest.
ls -1t "${BACKUP_DIR}"/db-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
ls -1t "${BACKUP_DIR}"/uploads-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "[backup ${STAMP}] done. current backups:"
du -sh "${BACKUP_DIR}" 2>/dev/null || true
ls -1t "${BACKUP_DIR}" | head -6

# Restore notes (do NOT run automatically):
#   DB:      ${COMPOSE} exec -T db pg_restore -U <user> -d <db> --clean < db-<stamp>.dump
#   uploads: tar -xzf uploads-<stamp>.tar.gz -C ${REMOTE_DIR}

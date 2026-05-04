#!/usr/bin/env bash
set -euo pipefail

VPS_HOST="root@89.167.39.152"
REMOTE_DIR="/opt/dispatchzero"

echo "[1/4] syncing source to ${VPS_HOST}:${REMOTE_DIR}"
# CRITICAL: --exclude 'uploads' protects runtime user data (capture photos
# and composed mission cards) from being wiped by --delete. The uploads/
# directory does not exist in the local repo, so without this exclude every
# deploy mirrors "no uploads" to the server and rsync --delete obliterates
# every user photo. Do not remove without a different persistence story.
rsync -az --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '.git' \
  --exclude 'tests' \
  --exclude '.env' \
  --exclude '.DS_Store' \
  --exclude '.claude' \
  --exclude 'uploads' \
  ./ "${VPS_HOST}:${REMOTE_DIR}/"

echo "[2/4] ensuring .env exists on remote"
ssh "${VPS_HOST}" "test -f ${REMOTE_DIR}/.env || (echo 'ERROR: ${REMOTE_DIR}/.env missing on remote — copy and fill it from .env.example' && exit 1)"

echo "[3/4] building and starting containers"
ssh "${VPS_HOST}" "cd ${REMOTE_DIR} && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build"

echo "[4/4] healthcheck"
sleep 5
curl -fsS https://dispatchzero.ataary.com/healthz && echo
echo "deploy ok"

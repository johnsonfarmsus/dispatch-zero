#!/usr/bin/env bash
set -euo pipefail

VPS_HOST="root@89.167.39.152"
REMOTE_DIR="/opt/dispatchzero"

echo "[1/2] syncing source (including tests) to ${VPS_HOST}:${REMOTE_DIR}"
rsync -az --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '.git' \
  --exclude '.env' \
  --exclude '.DS_Store' \
  --exclude '.claude' \
  ./ "${VPS_HOST}:${REMOTE_DIR}/"

echo "[2/2] running tests on VPS via docker compose run"
ssh "${VPS_HOST}" "cd ${REMOTE_DIR} && docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.test.yml run --rm --build test"

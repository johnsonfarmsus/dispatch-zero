#!/usr/bin/env bash
# Run the pytest suite on the remote VPS (via docker compose).
# Configure with DZ_VPS_HOST / DZ_REMOTE_DIR — see deploy/deploy.sh.
set -euo pipefail

# Optional: source local deployment overrides — same file deploy.sh uses.
if [[ -f "$(dirname "$0")/.env.local" ]]; then
  # shellcheck disable=SC1091
  source "$(dirname "$0")/.env.local"
fi

VPS_HOST="${DZ_VPS_HOST:?set DZ_VPS_HOST=user@host}"
REMOTE_DIR="${DZ_REMOTE_DIR:-/opt/dispatchzero}"

echo "[1/2] syncing source (including tests) to ${VPS_HOST}:${REMOTE_DIR}"
# CRITICAL: --exclude 'uploads' must be present alongside --delete or rsync
# will mirror "local has no uploads/" to the destination and wipe every
# captured user photo on the VPS. This script ran ~8 times during the
# Stage 1-3 push on 2026-06-02 and deleted 5 of Trevor's trip photos
# before this exclude was added. Same protection as in deploy.sh — do not
# remove without a different persistence story for /opt/dispatchzero/uploads.
# The .githooks/pre-commit hook now also blocks commits that violate this.
rsync -az --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '.git' \
  --exclude '.env' \
  --exclude '.DS_Store' \
  --exclude '.claude' \
  --exclude 'uploads' \
  ./ "${VPS_HOST}:${REMOTE_DIR}/"

echo "[2/2] running tests on VPS via docker compose run"
ssh "${VPS_HOST}" "cd ${REMOTE_DIR} && docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.test.yml run --rm --build test"

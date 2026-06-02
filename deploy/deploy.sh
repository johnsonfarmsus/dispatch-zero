#!/usr/bin/env bash
# Deploy Dispatch Zero to a remote VPS over SSH.
#
# Configure with environment variables (e.g. in your shell rc):
#   export DZ_VPS_HOST="root@your-server.example.com"
#   export DZ_REMOTE_DIR="/opt/dispatchzero"          # optional, this is the default
#   export DZ_HEALTHCHECK_URL="https://your-instance.example.com/healthz"  # optional
#
# Then: ./deploy/deploy.sh
set -euo pipefail

# Optional: source local deployment overrides (host, dir, healthcheck url).
# Keep this file gitignored — it's per-developer machine config.
if [[ -f "$(dirname "$0")/.env.local" ]]; then
  # shellcheck disable=SC1091
  source "$(dirname "$0")/.env.local"
fi

VPS_HOST="${DZ_VPS_HOST:?set DZ_VPS_HOST=user@host (e.g. root@your-server.example.com)}"
REMOTE_DIR="${DZ_REMOTE_DIR:-/opt/dispatchzero}"
HEALTHCHECK_URL="${DZ_HEALTHCHECK_URL:-}"

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
if [[ -n "${HEALTHCHECK_URL}" ]]; then
  curl -fsS "${HEALTHCHECK_URL}" && echo
else
  ssh "${VPS_HOST}" "curl -fsS http://localhost:8000/healthz" && echo
fi
echo "deploy ok"

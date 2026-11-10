#!/bin/bash
# Deploy the latest main to this server. Run on the server from /root/stock_platform:
#   ./scripts/deploy.sh
# Backs up the database first, rebuilds images, waits for health, prints status.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Backing up database"
./scripts/backup-db.sh

echo "== Fetching code"
git remote set-url origin https://github.com/bastian80821/nestLeap.git
git fetch origin main
before=$(git rev-parse --short HEAD)
git merge --ff-only origin/main
after=$(git rev-parse --short HEAD)
echo "   $before -> $after"

profiles=""
if grep -qE '^TRADING_BROKER=ibkr' .env 2>/dev/null; then profiles="--profile ibkr"; fi

if [ -n "$profiles" ]; then
  # The gateway runs as uid 1000; a fresh settings volume is created root-owned.
  docker volume create stock_platform_ib_settings >/dev/null
  docker run --rm --user 0 -v stock_platform_ib_settings:/d --entrypoint chown ghcr.io/gnzsnz/ib-gateway:stable -R 1000:1000 /d
fi

echo "== Building and starting"
docker compose $profiles up -d --build

echo "== Waiting for backend health"
for i in $(seq 1 30); do
  s=$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q backend)")
  [ "$s" = healthy ] && break
  sleep 5
done
echo "   backend: $s"
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
curl -sf https://nestleap.au/api/health && echo
./scripts/trading.sh status | head -12 || true
[ "$s" = healthy ] || { echo "!! backend not healthy — roll back with: git checkout $before && docker compose up -d --build"; exit 1; }

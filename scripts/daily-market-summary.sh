#!/bin/bash
# Force a fresh AI market summary (runs daily via cron).
#
# Crontab (every day 06:15 server time):
#   15 6 * * * cd /root/stock_platform && ./scripts/daily-market-summary.sh >> /var/log/nestleap-market.log 2>&1

set -e

API_URL="${API_URL:-https://nestleap.au}"
# Read the admin key from the project .env unless given (keeps it out of the crontab).
ADMIN_KEY="${ADMIN_KEY:-$(grep -E '^ADMIN_KEY=' "$(dirname "$0")/../.env" 2>/dev/null | cut -d= -f2-)}"
ADMIN_KEY="${ADMIN_KEY:?Set ADMIN_KEY in .env}"

echo "[$(date -Iseconds)] Refreshing market summary..."
curl -sf -X POST "$API_URL/api/admin/market-summary" \
  -H "X-Admin-Key: $ADMIN_KEY" || { echo "Failed"; exit 1; }
echo "[$(date -Iseconds)] Done."

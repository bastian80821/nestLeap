#!/bin/bash
# Weekly batch analysis + portfolio rebalance
# Add to crontab: 0 2 * * 0 /path/to/weekly-batch.sh
# (Runs every Sunday at 2 AM)

set -e

API_URL="${API_URL:-http://localhost:8000}"
ADMIN_KEY="${ADMIN_KEY:-changeme}"

echo "[$(date)] Starting weekly batch analysis..."
curl -sf -X POST "$API_URL/api/admin/batch/run" \
  -H "X-Admin-Key: $ADMIN_KEY" || { echo "Failed to start batch"; exit 1; }

echo "[$(date)] Batch started. Waiting for completion..."
while true; do
  sleep 30
  STATUS=$(curl -sf "$API_URL/api/batch/status")
  RUNNING=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin)['running'])")
  COMPLETED=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin)['completed'])")
  TOTAL=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin)['total'])")
  echo "[$(date)] Progress: $COMPLETED/$TOTAL"
  if [ "$RUNNING" = "False" ]; then
    break
  fi
done

echo "[$(date)] Batch complete. Refreshing market summary..."
curl -sf -X POST "$API_URL/api/admin/market-summary" \
  -H "X-Admin-Key: $ADMIN_KEY" > /dev/null || echo "Market summary failed"

echo "[$(date)] Rebalancing portfolio..."
curl -sf -X POST "$API_URL/api/admin/portfolio/rebalance" \
  -H "X-Admin-Key: $ADMIN_KEY" || echo "Rebalance failed"

echo "[$(date)] Weekly batch complete."

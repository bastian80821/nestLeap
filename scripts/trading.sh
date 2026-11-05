#!/bin/bash
# Run a broker-trading command inside the backend container, with a timestamped log line.
# Usage: ./scripts/trading.sh <status|propose|submit|sync [--eod]|reconcile|approve ID|reject ID|kill on|off|check>
# See scripts/crontab.txt for the schedule and docs/ROLLOUT.md for the rollout.
set -uo pipefail
cd "$(dirname "$0")/.."
echo "[$(date -Iseconds)] trading $*"
docker compose exec -T backend python -m app.trading.cli "$@"
status=$?
[ $status -ne 0 ] && echo "[$(date -Iseconds)] trading $* exited with $status"
exit $status

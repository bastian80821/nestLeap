#!/bin/bash
# Consistent SQLite backup (safe while the app is running) to /root/backups, keeps 30 days.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p /root/backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
docker compose exec -T backend python -c "
import sqlite3
src = sqlite3.connect('file:/app/data/nestleap.db?mode=ro', uri=True)
dst = sqlite3.connect('/app/data/backup.tmp.db')
src.backup(dst); dst.close(); src.close()"
docker compose cp backend:/app/data/backup.tmp.db "/root/backups/nestleap-$stamp.db" >/dev/null
docker compose exec -T backend rm -f /app/data/backup.tmp.db
# The simulated broker's account lives next to the database.
docker compose cp backend:/app/data/sim_broker.json "/root/backups/sim_broker-$stamp.json" >/dev/null 2>&1 || true
find /root/backups -name 'nestleap-*.db' -mtime +30 -delete
find /root/backups -name 'sim_broker-*.json' -mtime +30 -delete
echo "[$(date -Iseconds)] backup written: /root/backups/nestleap-$stamp.db"

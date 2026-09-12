#!/usr/bin/env bash
# PostgreSQL backup for Print FarmOS. Run from the host or inside the db container.
set -euo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT=${1:-"./backups/farmos-$STAMP.sql.gz"}
mkdir -p "$(dirname "$OUT")"
if command -v docker >/dev/null && docker compose ps db >/dev/null 2>&1; then
  docker compose exec -T db pg_dump -U farmos farmos | gzip > "$OUT"
else
  PGPASSWORD="${POSTGRES_PASSWORD:-farmos}" pg_dump -h 127.0.0.1 -U farmos farmos | gzip > "$OUT"
fi
echo "Wrote $OUT"

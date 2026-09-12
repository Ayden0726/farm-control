#!/usr/bin/env bash
# Host-side loop that applies Settings → Update Print FarmOS.
# Git credentials stay on the host (the containers cannot pull a private repo).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/data/update"
mkdir -p "$DIR"
echo $$ > "$DIR/agent.pid"

write_status() {
  local status="$1"
  local message="$2"
  python3 - "$status" "$message" "$DIR/status.json" <<'PY'
import json, sys, datetime
status, message, path = sys.argv[1], sys.argv[2], sys.argv[3]
payload = {
    "status": status,
    "message": message,
    "at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
}

write_status "idle" "Waiting for an update from Settings."

heartbeat() {
  while true; do
    date -u +%s > "$DIR/heartbeat"
    sleep 2
  done
}
heartbeat &
HB_PID=$!
trap 'kill "$HB_PID" 2>/dev/null || true' EXIT

while true; do
  if [[ -f "$DIR/request" ]]; then
    rm -f "$DIR/request"
    write_status "updating" "Pulling the latest Print FarmOS and rebuilding. This can take several minutes."
    set +e
    UPDATE_FROM_AGENT=1 "$ROOT/update.sh" > "$DIR/log.txt" 2>&1
    rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
      write_status "ok" "Update finished. Hard-refresh the browser if the UI looks old."
    else
      write_status "error" "Update failed. Check data/update/log.txt on the server, or run ./update.sh in a terminal."
    fi
  fi
  sleep 2
done

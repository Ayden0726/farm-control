#!/usr/bin/env bash
# Loop that applies Settings → Update Print FarmOS.
# Runs on the host (./scripts/ensure-update-agent.sh) or in the update-agent container.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/data/update"
mkdir -p "$DIR"
chmod 777 "$DIR" 2>/dev/null || true

if command -v flock >/dev/null 2>&1; then
  exec 9>"$DIR/agent.lock"
  if ! flock -n 9; then
    echo "Update agent already running (lock $DIR/agent.lock)."
    exit 0
  fi
fi

echo $$ > "$DIR/agent.pid"

if command -v flock >/dev/null 2>&1; then
  exec 9>"$DIR/agent.lock"
  if ! flock -n 9; then
    echo "Update agent already running (lock $DIR/agent.lock)."
    exit 0
  fi
fi

write_status() {
  local status="$1"
  local message="$2"
  local at
  at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"status":"%s","message":"%s","at":"%s"}\n' "$status" "$message" "$at" > "$DIR/status.json"
}

write_heartbeat() {
  date -u +%s > "$DIR/heartbeat"
}

git config --global --add safe.directory "$ROOT" 2>/dev/null || true

apply_restart_env() {
  local envf="$DIR/restart.env"
  if [[ ! -f "$envf" ]]; then
    return 0
  fi
  if [[ ! -f "$ROOT/.env" ]]; then
    touch "$ROOT/.env"
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    local key="${line%%=*}"
    local value="${line#*=}"
    if [[ ! "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]]; then
      continue
    fi
    if grep -qE "^${key}=" "$ROOT/.env"; then
      sed -i "s|^${key}=.*|${key}=${value}|" "$ROOT/.env"
    else
      printf '%s=%s\n' "$key" "$value" >> "$ROOT/.env"
    fi
  done < "$envf"
  rm -f "$envf"
}

write_status "idle" "Ready to update Print FarmOS."
write_heartbeat

while true; do
  write_heartbeat
  if [[ -f "$DIR/restart" ]]; then
    rm -f "$DIR/restart"
    write_status "restarting" "Restarting Print FarmOS so settings take effect."
    set +e
    {
      echo "Restarting FarmOS so settings take effect."
      apply_restart_env
      docker compose up -d --no-build --force-recreate backend worker slicer-worker
    } > "$DIR/log.txt" 2>&1
    rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
      write_status "ok" "Restart finished. Hard-refresh the browser if the UI looks old."
    else
      write_status "error" "Restart failed. Check data/update/log.txt or run docker compose up -d."
    fi
  fi
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

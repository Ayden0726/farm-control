#!/usr/bin/env bash
# Update Print FarmOS from git and rebuild containers. Database and uploads are kept.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f docker-compose.yml ]]; then
  echo "Run this from the Print FarmOS folder." >&2
  exit 1
fi

DOCKER=(docker)
if ! docker info >/dev/null 2>&1; then
  if sudo docker info >/dev/null 2>&1; then
    DOCKER=(sudo docker)
  else
    echo "Docker is not running. Start Docker, then re-run ./update.sh" >&2
    exit 1
  fi
fi
compose() { "${DOCKER[@]}" compose "$@"; }

if [[ -d .git ]]; then
  echo "==> Pulling latest code"
  git pull --ff-only
  APP_VERSION="$(git rev-parse --short HEAD)"
else
  echo "This folder is not a git clone. Copy a new release over it, then re-run ./update.sh" >&2
  exit 1
fi

if [[ -f .env ]]; then
  if grep -q '^APP_VERSION=' .env; then
    if command -v python3 >/dev/null 2>&1; then
      APP_VERSION="$APP_VERSION" python3 - <<'PY'
from pathlib import Path
import os, re
p = Path(".env")
text = re.sub(r"^APP_VERSION=.*$", f"APP_VERSION={os.environ['APP_VERSION']}", p.read_text(), count=1, flags=re.M)
if "APP_VERSION=" not in text:
    text += f"\nAPP_VERSION={os.environ['APP_VERSION']}\n"
p.write_text(text)
PY
    fi
  else
    echo "APP_VERSION=${APP_VERSION}" >> .env
  fi
fi
export APP_VERSION

echo "==> Rebuilding Print FarmOS ${APP_VERSION} (database and G-code uploads are kept)"
# Do not rebuild update-agent here — that container is applying this update.
compose up -d --build db redis backend worker slicer-worker frontend
compose up -d --no-build update-agent 2>/dev/null || true

detect_ip() {
  local ip=""
  ip="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }}' || true)"
  if [[ -z "$ip" ]]; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  fi
  if [[ -z "$ip" ]]; then
    ip="$(ip -4 addr show scope global 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1 || true)"
  fi
  echo "${ip:-127.0.0.1}"
}

HOST_URL=""
if [[ -f .env ]]; then
  HOST_URL="$(grep -E '^PUBLIC_APP_URL=' .env | tail -n1 | cut -d= -f2- || true)"
fi
if [[ -z "$HOST_URL" ]]; then
  HOST_URL="http://$(detect_ip):3000"
fi

echo
echo "Update complete."
echo "  Open:   ${HOST_URL}"
echo "  Local:  http://127.0.0.1:3000"
echo "  Slicer: ${HOST_URL%/}/slicer"
echo
echo "If the UI looks old, do a hard refresh (Ctrl+Shift+R)."
echo "Backup anytime with: ./scripts/backup.sh"

if [[ -z "${UPDATE_FROM_AGENT:-}" ]]; then
  chmod +x scripts/update-agent.sh scripts/ensure-update-agent.sh 2>/dev/null || true
  ./scripts/ensure-update-agent.sh || true
fi

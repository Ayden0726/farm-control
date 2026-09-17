#!/usr/bin/env bash
# Wipe Print FarmOS shop data and reinstall the stack.
# Usage (from the folder that contains this file):
#   ./wipe-and-reinstall.sh
#   ./wipe-and-reinstall.sh --host http://192.168.1.50:3000
#   bash wipe-and-reinstall.sh
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f install.sh || ! -f docker-compose.yml ]]; then
  echo "Run this from the Print FarmOS folder (the one with install.sh and docker-compose.yml)." >&2
  echo "Current folder: $PWD" >&2
  exit 1
fi

chmod +x install.sh 2>/dev/null || true

echo
echo "==> Wiping Print FarmOS and reinstalling"
echo "    This deletes the database (orders, queue, users, settings)."
echo "    .env (passwords and the public URL) is kept."
echo

if [[ -d .git ]] && command -v git >/dev/null 2>&1; then
  echo "==> Pulling latest code from Git"
  git pull --ff-only || echo "git pull skipped (no network or not a tracking branch)."
fi

exec bash install.sh --reset "$@"

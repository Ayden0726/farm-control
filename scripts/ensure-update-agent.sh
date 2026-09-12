#!/usr/bin/env bash
# Start (or reuse) the host updater that powers Settings → Update.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/data/update"
mkdir -p "$DIR"
chmod 777 "$DIR" 2>/dev/null || true
AGENT="$ROOT/scripts/update-agent.sh"
chmod +x "$AGENT" "$ROOT/update.sh" 2>/dev/null || true

agent_running() {
  if [[ -f "$DIR/agent.pid" ]]; then
    local pid
    pid="$(cat "$DIR/agent.pid" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

if agent_running; then
  echo "Update agent already running (pid $(cat "$DIR/agent.pid"))."
  exit 0
fi

if command -v systemctl >/dev/null 2>&1 && sudo -n true 2>/dev/null && systemctl is-system-running >/dev/null 2>&1; then
  unit="/etc/systemd/system/print-farmos-update-agent.service"
  user="${SUDO_USER:-$USER}"
  if [[ "$user" == "root" ]]; then
    user="${INSTALL_USER:-$USER}"
  fi
  cat > /tmp/print-farmos-update-agent.service <<EOF
[Unit]
Description=Print FarmOS one-click updater
After=docker.service network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=$AGENT
Restart=always
RestartSec=5
User=$user

[Install]
WantedBy=multi-user.target
EOF
  if sudo cp /tmp/print-farmos-update-agent.service "$unit" 2>/dev/null && sudo systemctl daemon-reload && sudo systemctl enable --now print-farmos-update-agent.service; then
    echo "Update agent installed as a system service (starts on boot)."
    exit 0
  fi
fi

nohup "$AGENT" >> "$DIR/agent.log" 2>&1 &
echo $! > "$DIR/agent.pid"
sleep 0.3
echo "Update agent started (pid $(cat "$DIR/agent.pid")). Settings → Update Print FarmOS is now available."
echo "Re-run ./install.sh after a reboot if the Update button stops working."

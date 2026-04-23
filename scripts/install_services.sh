#!/usr/bin/env bash
# install_services.sh — install pool-monitor daemon + pool-dashboard static server
# Serves dashboard at http://localhost:8080/dashboard/
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python3"
USER="$(whoami)"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: venv not found at $PROJECT_DIR/.venv — run:"
  echo "  cd $PROJECT_DIR && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "Installing pool-monitor services..."
echo "  Project dir : $PROJECT_DIR"
echo "  Python      : $PYTHON"
echo "  Running as  : $USER"
echo ""

# --- pool-monitor: polling daemon ---
sudo tee /etc/systemd/system/pool-monitor.service > /dev/null <<EOF
[Unit]
Description=Pool Filter Monitor (polling daemon)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON -m monitor.runner
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# --- pool-dashboard: static file server on :8080 ---
sudo tee /etc/systemd/system/pool-dashboard.service > /dev/null <<EOF
[Unit]
Description=Pool Dashboard (static file server on :8080)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON -m http.server 8080
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

for svc in pool-monitor pool-dashboard; do
  sudo systemctl enable "$svc"
  sudo systemctl restart "$svc"
  echo "  $svc: $(systemctl is-active $svc)"
done

echo ""
echo "Done. Dashboard: http://localhost:8080/dashboard/"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status pool-monitor pool-dashboard"
echo "  sudo journalctl -u pool-monitor -f"
echo "  sudo journalctl -u pool-dashboard -f"
echo "  sudo systemctl stop pool-monitor pool-dashboard"

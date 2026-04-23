#!/usr/bin/env bash
# install_service.sh — install pool-monitor as a systemd service
# Runs as the current user. Pool monitor polls during pump hours (7am-7pm).
set -euo pipefail

SERVICE_NAME="pool-monitor"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(which python3)"
USER="$(whoami)"

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "Installing pool-monitor systemd service..."
echo "  Project dir : $PROJECT_DIR"
echo "  Python      : $PYTHON"
echo "  Running as  : $USER"
echo ""

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Pool Filter Monitor
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

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

echo ""
echo "Service installed and started."
echo "Commands:"
echo "  sudo systemctl status $SERVICE_NAME"
echo "  sudo journalctl -u $SERVICE_NAME -f"
echo "  sudo systemctl stop $SERVICE_NAME"
echo "  sudo systemctl disable $SERVICE_NAME"

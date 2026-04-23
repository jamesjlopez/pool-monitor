#!/bin/bash
# Installs pool-monitor and pool-dashboard as macOS launchd user agents.
# Run from the project root: bash scripts/install_macos_services.sh

set -e

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT/.venv/bin/python3"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

if [ ! -f "$VENV_PYTHON" ]; then
  echo "ERROR: venv not found at $VENV_PYTHON"
  echo "Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

mkdir -p "$LAUNCH_AGENTS"

for SERVICE in pool-monitor pool-dashboard; do
  PLIST_SRC="$PROJECT/scripts/com.james.$SERVICE.plist"
  PLIST_DST="$LAUNCH_AGENTS/com.james.$SERVICE.plist"

  sed \
    -e "s|REPLACE_WITH_PROJECT_PATH|$PROJECT|g" \
    -e "s|REPLACE_WITH_VENV_PYTHON|$VENV_PYTHON|g" \
    "$PLIST_SRC" > "$PLIST_DST"

  launchctl unload "$PLIST_DST" 2>/dev/null || true
  launchctl load "$PLIST_DST"
  echo "Loaded: $PLIST_DST"
done

echo ""
echo "Services running. Check logs at $PROJECT/logs/"
echo "Dashboard: http://localhost:8080/dashboard/"

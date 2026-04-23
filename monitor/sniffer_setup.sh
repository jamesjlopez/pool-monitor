#!/usr/bin/env bash
# sniffer_setup.sh — install mitmproxy and run either discovery or monitoring mode
# Usage:
#   ./monitor/sniffer_setup.sh discover   (Phase 1: capture all Pentair app traffic)
#   ./monitor/sniffer_setup.sh monitor    (Phase 2+: parse and feed into engine)
set -euo pipefail

MODE="${1:-discover}"
PROXY_PORT=8080
# In WSL2, hostname -I gives the WSL virtual IP, not the Windows LAN IP.
# Try to get the Windows host's actual WiFi IP via /etc/resolv.conf nameserver heuristic,
# then fall back to hostname -I.
WSL_HOST_IP=$(grep nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}' | head -1)
HOST_IP="${WSL_HOST_IP:-$(hostname -I | awk '{print $1}')}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Checking mitmproxy..."
if ! command -v mitmdump &>/dev/null; then
    echo "Installing mitmproxy..."
    pip install mitmproxy 2>/dev/null || pip3 install mitmproxy
fi

echo ""
echo "======================================================"
echo "  DEVICE SETUP (do this once)"
echo "======================================================"
echo "NOTE: Running in WSL2. iPhone must use your Windows WiFi IP, not the WSL IP."
echo "      Run 'ipconfig' in Windows PowerShell to find your WiFi IPv4 address."
echo "      Then forward the port (run as Admin in PowerShell):"
echo "        netsh interface portproxy add v4tov4 listenport=$PROXY_PORT listenaddress=0.0.0.0 connectport=$PROXY_PORT connectaddress=$(hostname -I | awk '{print $1}')"
echo "        netsh advfirewall firewall add rule name=mitmproxy dir=in action=allow protocol=TCP localport=$PROXY_PORT"
echo ""
echo "1. On your iPhone, go to Settings > Wi-Fi > your network > Configure Proxy"
echo "2. Set to Manual:"
echo "     Server: <your Windows WiFi IP from ipconfig>  (guessed: $HOST_IP)"
echo "     Port:   $PROXY_PORT"
echo "     Authentication: OFF"
echo "3. Open Safari and visit: http://mitm.it"
echo "   Download and install the iOS certificate."
echo "4. Go to Settings > General > About > Certificate Trust Settings"
echo "   Enable full trust for the mitmproxy certificate."
echo "5. Open the Pentair Home app — navigate to the pump status screen."
echo "======================================================"
echo ""

if [ "$MODE" = "discover" ]; then
    echo "==> DISCOVERY MODE — logging all traffic to logs/discovery/"
    echo "    Open Pentair Home app on your phone and:"
    echo "      - View pump status"
    echo "      - Change speed (if safe to do so)"
    echo "      - Turn pump on/off (if safe to do so)"
    echo "    Then Ctrl-C and inspect logs/discovery/*.jsonl"
    echo ""
    mitmdump \
        --listen-port "$PROXY_PORT" \
        --ssl-insecure \
        -s "$SCRIPT_DIR/discover.py"
else
    echo "==> MONITOR MODE — parsing traffic and feeding into engine"
    mitmdump \
        --listen-port "$PROXY_PORT" \
        --ssl-insecure \
        -s "$SCRIPT_DIR/packet_parser.py"
fi

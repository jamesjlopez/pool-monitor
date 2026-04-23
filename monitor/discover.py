#!/usr/bin/env python3
"""
discover.py — mitmproxy addon for Pentair API discovery.

Run with:
    mitmdump -s monitor/discover.py --listen-port 8080 --ssl-insecure

Then configure your iPhone proxy to point at this machine:8080,
install the mitmproxy CA cert (visit http://mitm.it), trust it in
Settings > General > About > Certificate Trust Settings, and open
the Pentair Home app. All traffic will be logged to logs/discovery/.

After capture, inspect logs/discovery/*.json to find:
  - The base URL (local IP or cloud endpoint)
  - Auth headers (Authorization, x-api-key, cookie, etc.)
  - Endpoints that return RPM / watts / flow data
  - Endpoints that accept speed/on-off commands

Document findings in docs/api_notes.md.
"""

import json
import logging
import os
import time
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs" / "discovery"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Keywords that suggest a response contains pump telemetry
_TELEMETRY_HINTS = {
    "rpm", "flow", "gph", "watt", "power", "speed", "pump",
    "pressure", "psi", "intelliflo", "pentair", "filter",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("discover")

_session_file = LOG_DIR / f"session_{int(time.time())}.jsonl"
_telemetry_file = LOG_DIR / f"telemetry_{int(time.time())}.jsonl"

log.info("Logging ALL traffic to %s", _session_file)
log.info("Telemetry candidates to %s", _telemetry_file)


def _looks_like_telemetry(body: str) -> bool:
    lower = body.lower()
    return any(hint in lower for hint in _TELEMETRY_HINTS)


def _try_parse_json(text: str) -> dict | list | None:
    try:
        return json.loads(text)
    except Exception:
        return None


class DiscoveryAddon:
    def response(self, flow):
        try:
            self._handle(flow)
        except Exception as e:
            log.error("Error handling flow: %s", e)

    def _handle(self, flow):
        url = str(flow.request.url)
        method = flow.request.method
        status = flow.response.status_code
        req_body = flow.request.text or ""
        resp_body = flow.response.text or ""

        entry = {
            "ts": time.time(),
            "method": method,
            "url": url,
            "status": status,
            "req_headers": dict(flow.request.headers),
            "req_body": _try_parse_json(req_body) or req_body[:500],
            "resp_headers": dict(flow.response.headers),
            "resp_body": _try_parse_json(resp_body) or resp_body[:2000],
        }

        # Write every request to session log
        with open(_session_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

        # If the response looks like pump telemetry, highlight it
        if _looks_like_telemetry(resp_body):
            log.info("*** TELEMETRY CANDIDATE *** %s %s → %s", method, url, status)
            log.info("    Response: %s", resp_body[:300])
            with open(_telemetry_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        else:
            log.debug("%s %s → %s", method, url, status)


addons = [DiscoveryAddon()]

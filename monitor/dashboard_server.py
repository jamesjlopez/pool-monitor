"""Dashboard file server with durable, typed maintenance records."""

import json
import os
import sys
import threading
from datetime import datetime, timezone, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

KINDS = {"filter_element", "filter_canister", "surface_skimmer", "pump_basket"}
LOCK = threading.Lock()


def validate_event(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid maintenance entry")
    event_id = str(UUID(value.get("id", "")))
    kind = value.get("kind")
    if kind not in KINDS:
        raise ValueError("Choose a maintenance action")
    ts = datetime.fromisoformat(value.get("ts", "").replace("Z", "+00:00"))
    if ts.tzinfo is None or ts > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("Choose a valid date and time, not in the future")
    notes = value.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 1000:
        raise ValueError("Notes must be at most 1,000 characters")
    return {"id": event_id, "kind": kind, "ts": ts.astimezone(timezone.utc).isoformat(),
            "notes": notes.strip(), "recorded_at": datetime.now(timezone.utc).isoformat()}


class DashboardHandler(SimpleHTTPRequestHandler):
    maintenance_path = Path("logs/maintenance.json")

    def reply(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_events(self):
        if not self.maintenance_path.exists():
            return []
        events = json.loads(self.maintenance_path.read_text())
        if not isinstance(events, list):
            raise ValueError("Maintenance history is invalid")
        return events

    def do_GET(self):
        if urlsplit(self.path).path != "/api/maintenance":
            return super().do_GET()
        try:
            with LOCK:
                events = self.read_events()
            self.reply(200, events)
        except (OSError, ValueError):
            self.reply(500, {"error": "Could not read maintenance history"})

    def do_POST(self):
        if urlsplit(self.path).path != "/api/maintenance":
            return self.reply(404, {"error": "Not found"})
        origin = self.headers.get("Origin")
        host = self.headers.get("X-Forwarded-Host", self.headers.get("Host", ""))
        if origin and urlsplit(origin).netloc != host:
            return self.reply(403, {"error": "Use this dashboard to save maintenance"})
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, {"error": "JSON required"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                raise ValueError("Invalid entry size")
            event = validate_event(json.loads(self.rfile.read(size)))
        except (ValueError, TypeError, AttributeError):
            return self.reply(400, {"error": "Check the action, date, and notes"})
        try:
            with LOCK:
                events = self.read_events()
                existing = next((item for item in events if item["id"] == event["id"]), None)
                if existing:
                    if any(existing[k] != event[k] for k in ("kind", "ts", "notes")):
                        return self.reply(409, {"error": "Entry already saved with different details"})
                else:
                    events.append(event)
                    events.sort(key=lambda item: item["ts"])
                    self.maintenance_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.maintenance_path.with_suffix(".tmp")
                    with temporary.open("w") as output:
                        json.dump(events, output, indent=2)
                        output.flush()
                        os.fsync(output.fileno())
                    temporary.replace(self.maintenance_path)
            self.reply(200, existing or event)
        except (OSError, ValueError, KeyError):
            self.reply(500, {"error": "Could not save maintenance; please retry"})


if __name__ == "__main__":
    ThreadingHTTPServer(("", int(sys.argv[1]) if len(sys.argv) > 1 else 8081), DashboardHandler).serve_forever()

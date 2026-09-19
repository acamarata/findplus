#!/usr/bin/env python3
"""Stand in for the findplus daemon so the tray can be driven through every state.

Purpose    : Serve /api/health, /api/status and /api/widget with a payload the
             caller picks at run time, so Find+.app can be screenshotted in
             every tray state with no account and no poller.
Inputs     : POST /set-state {"mode": ...} and POST /set-widget <payload>.
Outputs    : JSON on the GET routes; 401 when locked and 503 when down, which
             the client reads as Locked and Down.
Constraints: binds 127.0.0.1:8647, keeps nothing on disk, uses the api-contract
             field names, invents no top-level "state" key, and fails both
             probes when down because the tray reads /api/status, not health.
"""

import http.server
import json
from datetime import UTC, datetime, timedelta

MODE, WIDGET = "ok", {}
HEALTH = {"status": "ok", "app": "findplus", "version": "1.0.0"}


def build_payload(mode: str) -> dict:
    def iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    now, stale, error = datetime.now(UTC), mode == "stale", mode == "error"
    return {
        "provider_health": [],
        "alerts_configured": True,
        "last_error_type": "auth" if error else None,
        "consecutive_failures": 4 if error else 0,
        "tracked_count": 3,
        "last_poll_at": iso(now - timedelta(minutes=32 if stale else 2)),
        "next_poll_at": iso(now + timedelta(minutes=3)),
    }


PAYLOAD = build_payload(MODE)


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if MODE == "down" and self.path in ("/api/health", "/api/status"):
            return self._bare(503)
        if self.path == "/api/health":
            return self._json(HEALTH)
        if self.path == "/api/status":
            return self._bare(401) if MODE == "locked" else self._json(PAYLOAD)
        if self.path == "/api/widget":
            return self._json(WIDGET)
        self._bare(404)

    def _bare(self, code: int) -> None:
        """Answer with a status line and no body."""
        self.send_response(code)
        self.end_headers()

    def do_POST(self) -> None:
        global MODE, PAYLOAD, WIDGET
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        if self.path == "/set-state":
            MODE = data["mode"]
            PAYLOAD = build_payload(MODE)
        elif self.path == "/set-widget":
            WIDGET = data
        self._bare(204)

    def _json(self, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a) -> None:  # keep the console clean
        pass


if __name__ == "__main__":
    http.server.HTTPServer(("127.0.0.1", 8647), H).serve_forever()

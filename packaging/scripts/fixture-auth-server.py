#!/usr/bin/env python3
"""Fixture auth stub: answer the 3 auth routes (routes_auth.py's real shapes)
so #/setup runs with no real account; proxy everything else to the daemon on
DAEMON_PORT. Never 8647 (owner's port) or DAEMON_PORT as our own listen port
(self-loop would hang every unmatched request, F12)."""
import http.client
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

DAEMON_PORT = 18648
_NOW = datetime.now(UTC).isoformat()
STATUS = {"providers": [
    {"id": "google-find-hub", "signed_in": True, "account": "test@example.invalid",
     "method": "chrome", "last_checked": _NOW, "needs": []},
    {"id": "apple-find-my", "signed_in": False, "account": None,
     "method": "apple-2fa", "last_checked": _NOW, "needs": []},
]}
PROGRESS = {"state": "done", "message": "Signed in as test@example.invalid.", "chrome_found": True}
HOP = ("host", "content-length", "transfer-encoding", "connection")

class H(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/api/auth/status":
            return self._json(200, STATUS)
        if self.path.startswith("/api/auth/google/progress"):
            return self._json(200, PROGRESS)
        self._proxy("GET")
    def do_POST(self) -> None:
        if self.path == "/api/auth/google/start":
            return self._json(202, {"job_id": "fixture-google-job-1"})
        self._proxy("POST")
    def do_PATCH(self) -> None:
        self._proxy("PATCH")
    def _proxy(self, method: str) -> None:
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n) if n else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        conn = http.client.HTTPConnection("127.0.0.1", DAEMON_PORT, timeout=30)
        conn.request(method, self.path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in ("transfer-encoding", "connection"):
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)
        conn.close()
    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_a) -> None:
        pass
if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 18647), H).serve_forever()

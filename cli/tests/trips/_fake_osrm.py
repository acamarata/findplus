"""A loopback OSRM stand-in. Records every request path; never leaves 127.0.0.1."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

LINE = [[-80.1, 41.1], [-80.09, 41.11], [-80.08, 41.12]]


class FakeOsrm:
    def __init__(self, match: str = "ok", route: str = "ok") -> None:
        self.modes = {"match": match, "route": route}
        self.requests: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                outer.requests.append(self.path)
                kind = "match" if "/match/" in self.path else "route"
                mode = outer.modes[kind]
                if mode == "500":
                    self.send_response(500)
                    self.end_headers()
                    return
                body = (
                    b"not json" if mode == "junk" else json.dumps(outer._body(kind, mode)).encode()
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @staticmethod
    def _body(kind: str, mode: str) -> dict:
        if mode == "nomatch":
            return {"code": "NoMatch"}
        geom = {"type": "LineString", "coordinates": LINE}
        key = "matchings" if kind == "match" else "routes"
        return {"code": "Ok", key: [{"geometry": geom}]}

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self) -> FakeOsrm:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()

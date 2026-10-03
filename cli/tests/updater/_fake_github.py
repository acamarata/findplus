"""A fake GitHub releases API on 127.0.0.1 for the updater tests.

Purpose    : Answer GET /repos/acamarata/findplus/releases/latest and the asset
             downloads from a dict the test controls, and count every request,
             so a test can prove the updater made none.
Inputs     : `FakeGitHub.publish(version, dmg_bytes, sha=None, **release)`.
Outputs    : `.base` (set as FINDPLUS_UPDATE_API), `.hits` (request paths).
Constraints: Loopback only; the suite's socket guard refuses anything else.
"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LATEST = "/repos/acamarata/findplus/releases/latest"


class FakeGitHub:
    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, bytes]] = {LATEST: (404, b"{}")}
        self.hits: list[str] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                fake.hits.append(self.path)
                code, body = fake.routes.get(self.path, (404, b"not found"))
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: Any) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def publish(self, version: str, dmg: bytes, *, sha: str | None = None, **extra: Any) -> str:
        """Serve `version` as the latest release with a dmg and its .sha256."""
        name = f"FindPlus-{version}-aarch64.dmg"
        dmg_path = f"/dl/v{version}/{name}"
        digest = sha or hashlib.sha256(dmg).hexdigest()
        self.routes[dmg_path] = (200, dmg)
        self.routes[dmg_path + ".sha256"] = (200, f"{digest}  {name}\n".encode())
        body = {
            "tag_name": f"v{version}",
            "html_url": f"{self.base}/releases/v{version}",
            "draft": False,
            "prerelease": False,
            "assets": [
                {"name": name, "browser_download_url": self.base + dmg_path},
                {"name": f"{name}.sha256", "browser_download_url": f"{self.base}{dmg_path}.sha256"},
            ],
            **extra,
        }
        self.routes[LATEST] = (200, json.dumps(body).encode())
        return name

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

"""Helpers for the day-story tests: open a day, and a fake OSRM routing server."""

# ruff: noqa: E501, RUF100

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


async def open_day(page, trips_server, day_key, device="TAG-SON", prefs=None):
    """Load the dashboard on a seeded day with `device` in the Show filter."""
    day = trips_server["days"][day_key]
    init = f"localStorage.setItem('findplus.deviceFilter','{device}');" if device else ""
    for k, v in (prefs or {}).items():
        init += f"localStorage.setItem('{k}','{v}');"
    await page.add_init_script(init)
    await page.goto(trips_server["base"] + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]")
    await page.evaluate(f"import('/static/app/timeline.js').then(m => m.loadDay('{day}'))")
    return day


def start_fake_osrm():
    """A loopback OSRM that draws a corner path for any /match request. Returns (url, hits, stop)."""
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            coords = [c.split(",") for c in self.path.split("?")[0].rsplit("/", 1)[1].split(";")]
            line = [[float(a), float(b)] for a, b in coords]
            body = {
                "code": "Ok",
                "matchings": [{"geometry": {"type": "LineString", "coordinates": line}}],
            }
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}", hits, server.shutdown

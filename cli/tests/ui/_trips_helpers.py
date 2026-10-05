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
    if device:
        # The day body lives in the tracker focus view now (dashboard 1.3).
        await page.evaluate(
            "d => window.dispatchEvent(new CustomEvent('findplus:focus-tracker', { detail: { device_id: d } }))",
            device,
        )
        await page.wait_for_selector("#fp-latest-focus:not([hidden])")
        await page.wait_for_load_state("networkidle")  # the focus reload has landed
        if (prefs or {}).get("findplus.dayView") == "raw":
            await page.click("#fp-latest-focus [data-view=raw]")
    return day


async def focus_sightings(page, device="TAG-SON"):
    """Focus `device` and show Every sighting (after a reload that dropped the focus)."""
    await page.evaluate(
        "d => window.dispatchEvent(new CustomEvent('findplus:focus-tracker', { detail: { device_id: d } }))",
        device,
    )
    await page.click("#fp-latest-focus [data-view=raw]")


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


async def show_legacy_story(page):
    """The all-trackers day story (group lanes) is not part of focus; park the old body in Latest to test it."""
    await page.evaluate(
        "import('/static/app/legacy_day_host.js').then((m) => m.parkDayHost(document.getElementById('tab-latest'), 'story'))"
    )

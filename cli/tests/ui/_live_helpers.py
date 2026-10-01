"""Shared helpers for the live-status browser tests (banner, refresh, empty states).

Purpose    : Drive the dashboard through the states a real first sign-in passes
             through (locked, polling, no new locations, data arrives) by
             answering GET /api/status from a mutable holder, so one page can
             move from state to state the way the daemon would move it.
Inputs     : A Playwright page and the live_server base URL.
Outputs    : `StatusFeed` (the holder + route), run/status builders, openers.
Constraints: Only /api/status and /api/auth/status are stubbed; the timeline,
             devices and map still come from the real seeded server, so a
             refresh is proven by the requests it makes. No provider contact.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ._signin_helpers import reply, status_body

#: The seeded tracked devices (_seed_script.py): TAG-HOME is labelled "Ali's Keys".
TRACKED = ("TAG-HOME", "TAG-AWAY", "TAG-STALE")


def run_row(run_id: int, status: str, device_id: str | None, new: int = 0) -> dict:
    """One serialized PollRun, started a moment ago."""
    started = (datetime.now(UTC) - timedelta(seconds=20 + run_id % 7)).isoformat()
    return {
        "id": run_id,
        "status": status,
        "started_at_utc": started,
        "started_at_local": started,
        "finished_at_utc": started,
        "duration_ms": 900,
        "observations_returned": new,
        "observations_new": new,
        "error_type": None if status in ("ok", "no_location") else status,
        "error_message": None,
    }


class StatusFeed:
    """Answers /api/status with `body`; tests replace `body` to move time on."""

    def __init__(self, real: dict) -> None:
        self.real = real
        self.body = real
        self.hits = 0

    def cycle(self, statuses: dict[str, tuple[str, int]], run_id: int, **top) -> dict:
        """The real status with each tracked device's last run replaced.

        `statuses` maps device id -> (poll status, new observations). The
        top-level last_poll is the run of the first device named in `statuses`,
        as the API would report it.
        """
        body = dict(self.real, devices=[dict(d) for d in self.real["devices"]])
        first = None
        for index, device in enumerate(body["devices"]):
            if device["device_id"] not in statuses:
                continue
            status, new = statuses[device["device_id"]]
            device["last_poll"] = run_row(run_id + index, status, device["device_id"], new)
            if device["device_id"] == next(iter(statuses)):
                first = device["last_poll"]
        body["last_poll"] = first
        ok = first is not None and first["status"] in ("ok", "no_location")
        body["last_successful_poll"] = first if ok else self.real["last_successful_poll"]
        body.update({"poller_running": True, **top})
        self.body = body
        return body

    async def route(self, route) -> None:
        self.hits += 1
        await route.fulfill(json=self.body)


async def real_status(page, base_url: str) -> dict:
    return await (await page.request.get(base_url + "/api/status")).json()


async def feed_for(page, base_url: str) -> StatusFeed:
    """Install the status feed on `page` (before navigation) from the real body."""
    feed = StatusFeed(await real_status(page, base_url))
    await page.route("**/api/status*", feed.route)
    return feed


async def stub_google_locked(page, locked: bool = True) -> None:
    """Auth status: Google signed in, with or without the E2EE key locked."""
    needs = ["shared_key"] if locked else []
    await page.route("**/api/auth/status", reply(status_body(google=True, needs_g=needs)))


async def open_dashboard(page, base_url: str) -> None:
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']", timeout=15000)


async def show_day(page, day: str) -> None:
    """Load `day` through the app's own loadDay(), as the day picker does."""
    await page.evaluate("(d) => import('/static/app/timeline.js').then((m) => m.loadDay(d))", day)


async def reload_status(page) -> None:
    """Run status_view.js's loadStatus(), the call every refresh makes."""
    await page.evaluate("() => import('/static/app/status_view.js').then((m) => m.loadStatus())")

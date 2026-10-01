"""A lock that fires while Poll Now runs must not get tracker names written behind it (r1 #6)."""

from __future__ import annotations

import contextlib

import pytest

from ._live_helpers import open_dashboard
from .test_lock import PIN
from .test_lock_purge import _setup_purge_fixture, _teardown_purge_fixture

pytestmark = pytest.mark.asyncio(loop_scope="session")

LEAK = "Leaky Tracker Name"


async def test_poll_now_summary_is_dropped_when_the_app_locks_mid_request(
    page, base_url, reset_alert_and_observation_state
):
    await _setup_purge_fixture(page, base_url)
    try:

        async def locked_midway(route):
            # The user (or the idle timer) locks while the request is in flight.
            await page.locator("#btn-lock").dispatch_event("click")
            await page.wait_for_selector("#lock-screen:not(.hidden)")
            await route.fulfill(
                json={
                    "status": "ok",
                    "devices_polled": 1,
                    "observations_returned": 1,
                    "observations_new": 1,
                    "duplicates": 0,
                    "results": [
                        {
                            "device_id": "TAG-HOME",
                            "device_name": LEAK,
                            "status": "ok",
                            "observations_new": 1,
                            "duplicates": 0,
                            "error": None,
                        }
                    ],
                }
            )

        await page.route("**/api/poll-now", locked_midway)
        await open_dashboard(page, base_url)
        await page.click("#btn-poll")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        await page.wait_for_timeout(1500)  # let reload() and the summary code run
        assert LEAK not in await page.content()
        assert (await page.locator("#alert").inner_text()).strip() == ""
    finally:
        with contextlib.suppress(Exception):
            await page.fill("#lock-pin", PIN)
            await page.click("#lock-submit")
        await _teardown_purge_fixture(page, base_url)

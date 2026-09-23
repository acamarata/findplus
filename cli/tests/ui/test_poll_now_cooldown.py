"""Browser test for Poll Now's client-side cooldown (UAT5 N50).

A second Poll Now within the server's one-per-minute limit used to reach the
API and come back 429, logging a console error even though the on-screen
message (devices_actions.js's showAlert call) was already fine. pollNow()
now disables the button for the cooldown -- the server's own remaining wait
on a 429, or a guess at the full window after a poll it made itself -- so a
second click inside that window never fires a second request.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_dashboard(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")


async def test_two_quick_clicks_send_one_poll_request(page, base_url):
    calls: list[str] = []

    async def handle_poll(route):
        calls.append(route.request.url)
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"devices_polled": 0, "observations_new": 0, "results": []}),
        )

    await page.route("**/api/poll-now", handle_poll)
    await _open_dashboard(page, base_url)

    btn = page.locator("#btn-poll")
    await btn.click()
    assert await btn.is_disabled()
    # A click landing on an already-disabled button (dispatched directly,
    # since Playwright's own click() refuses a disabled target) must not
    # queue a second request.
    await page.evaluate("document.getElementById('btn-poll').click()")

    await page.wait_for_function(
        "() => document.getElementById('btn-poll').textContent !== 'Polling…'",
        timeout=15000,
    )
    assert len(calls) == 1

    # The real regression: a click after the first poll had already finished,
    # but still inside the server's one-per-minute window. The button used to
    # re-enable immediately once the request settled; it now stays disabled
    # for the cooldown, so a click here cannot fire a second request either.
    assert await btn.is_disabled()
    await page.evaluate("document.getElementById('btn-poll').click()")
    await page.wait_for_timeout(200)
    assert len(calls) == 1

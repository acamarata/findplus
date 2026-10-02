"""A redraw that failed once is retried on the next look, not lost (r1 review #8)."""

from __future__ import annotations

import pytest

from ._live_helpers import feed_for, open_dashboard, stub_google_locked

pytestmark = pytest.mark.asyncio(loop_scope="session")

LOCKED = {t: ("needs_shared_key", 0) for t in ("TAG-HOME", "TAG-AWAY", "TAG-STALE")}
GOOD = {t: ("ok", 1) for t in ("TAG-HOME", "TAG-AWAY", "TAG-STALE")}


async def test_a_failed_device_fetch_is_retried_when_the_status_has_not_changed_again(
    page, base_url
):
    await page.clock.install()
    await stub_google_locked(page)
    feed = await feed_for(page, base_url)
    feed.cycle(LOCKED, 300, observations_today=0)
    await open_dashboard(page, base_url)
    await page.locator("#alert .alert-action").wait_for(state="visible")

    state = {"fail": 1, "seen": 0}

    async def devices(route):
        state["seen"] += 1
        if state["fail"] > 0:
            state["fail"] -= 1
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/api/devices", devices)
    feed.cycle(GOOD, 310, observations_today=7, observations_total=9)  # then stays the same
    await page.clock.run_for(11000)
    await page.wait_for_function(
        "() => document.getElementById('card-today').textContent === '7'", timeout=15000
    )
    for _ in range(60):
        if state["seen"] >= 2:
            break
        await page.clock.run_for(11000)
        await page.wait_for_timeout(100)
    assert state["seen"] >= 2, "the failed redraw was never retried"

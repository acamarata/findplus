"""A lock landing while the dashboard reacts to a sign-in leaves no "Polling" wait (r1 #16)."""

from __future__ import annotations

import contextlib
import json

import pytest

from ._live_helpers import open_dashboard
from ._signin_helpers import status_body
from .test_lock import PIN
from .test_lock_purge import _setup_purge_fixture, _teardown_purge_fixture

pytestmark = pytest.mark.asyncio(loop_scope="session")

EVENT = "() => window.dispatchEvent(new CustomEvent('findplus:accounts-changed'))"


async def test_accounts_changed_during_a_lock_does_not_await_a_poll(
    page, base_url, reset_alert_and_observation_state
):
    await _setup_purge_fixture(page, base_url)
    armed = {"on": False}
    try:

        async def auth_status(route):
            if armed["on"]:
                armed["on"] = False
                # The lock arrives while the "is anyone signed in" read is in flight.
                await page.locator("#btn-lock").dispatch_event("click")
                await page.wait_for_selector("#lock-screen:not(.hidden)")
            await route.fulfill(
                content_type="application/json", body=json.dumps(status_body(google=True))
            )

        await page.route("**/api/auth/status", auth_status)
        await open_dashboard(page, base_url)
        armed["on"] = True
        await page.evaluate(EVENT)
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        await page.wait_for_timeout(1500)
        awaiting = await page.evaluate(
            "() => import('/static/app/state.js').then((m) => m.state.awaitingPoll)"
        )
        assert awaiting is None
    finally:
        with contextlib.suppress(Exception):
            await page.fill("#lock-pin", PIN)
            await page.click("#lock-submit")
        await _teardown_purge_fixture(page, base_url)

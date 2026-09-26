"""Browser tests for the wizard's Done step recovery state (UAT6-N19).

Own file rather than an addition to test_setup_wizard.py, which is already
near the 300-line file cap (PRI rule 7) -- the same reason
test_setup_wizard_devices_refresh.py exists.

"You're set up · 0 devices tracked" with nobody signed in and nothing
tracked read as a success, when it is exactly the state that most needs
fixing. done.js now asks GET /api/auth/status alongside GET /api/devices: if
neither anything is signed in nor tracked, it swaps the heading and summary
for a plain "nothing connected yet" pair and offers a button straight back to
Sign-in, using the Wizard's own `goToStep()` (wizard.js, UAT6-N04's ctx
additions) rather than a plain Next/Back.
"""

from __future__ import annotations

import json

import pytest

from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _set_completed_at(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _set_last_step(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.last_step",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


def _no_provider_signed_in(route):
    return route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(
            {
                "providers": [
                    {"id": "google-find-hub", "signed_in": False, "account": None, "needs": []},
                    {"id": "apple-find-my", "signed_in": False, "account": None, "needs": []},
                ]
            }
        ),
    )


async def test_done_shows_nothing_connected_when_signed_out_and_untracked(page, base_url):
    async def devices(route):
        # `bootDashboard()`'s own loadDevices() (devices.js) runs before the
        # wizard ever mounts (applyHashRoute() is its own last step) and reads
        # `body.devices` unconditionally -- a mock without it throws there and
        # the wizard never opens at all (test_setup_wizard.py's own
        # test_done_shows_the_servers_tracked_count_on_a_resumed_session mock
        # already carries this for the same reason).
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"tracked_count": 0, "devices": []}),
        )

    await page.route("**/api/devices", devices)
    await page.route("**/api/auth/status", _no_provider_signed_in)

    await _set_completed_at(page, base_url, None)
    try:
        await _set_last_step(page, base_url, "done")
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("#setup-view p[data-ready='true']", timeout=15000)

        heading = await page.locator("#setup-view h2").first.text_content()
        assert heading != "You're set up", heading
        summary = await page.locator("#setup-view p").first.inner_text()
        assert "set up" not in summary.lower(), summary

        button = page.get_by_role("button", name="Go to Sign-in")
        await button.wait_for(state="visible")
        await button.click()
        await page.wait_for_selector("#fp-setup-signin-status", timeout=15000)
        progress = await page.locator(".fp-wizard-progress-text").inner_text()
        assert progress.strip().startswith("2"), progress
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_done_keeps_the_celebration_when_tracking_something(page, base_url):
    """Signed out but still showing 3 tracked devices (a resumed session that
    skipped straight to Done) must NOT be read as the empty state -- only
    "nothing signed in AND nothing tracked" is."""

    async def devices(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"tracked_count": 3, "devices": []}),
        )

    await page.route("**/api/devices", devices)
    await page.route("**/api/auth/status", _no_provider_signed_in)

    await _set_completed_at(page, base_url, None)
    try:
        await _set_last_step(page, base_url, "done")
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("#setup-view p[data-ready='true']", timeout=15000)

        heading = await page.locator("#setup-view h2").first.text_content()
        assert heading == "You're set up", heading
        summary = await page.locator("#setup-view p").first.inner_text()
        assert summary == "3 devices tracked.", summary
        assert await page.locator("#fp-setup-done-signin").is_hidden()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)

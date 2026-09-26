"""Browser tests for a failed device refresh (UAT6-N03, BLOCKING/data loss).

Split out of test_setup_wizard_devices.py (2026-09-26, PRI rule-7 size cap):
that file was already at the 300-line ceiling once its own Devices/Groups
coverage landed, so this one regression gets its own file rather than pushing
it over.

Before this fix, `refresh()` (setup_steps/devices.js) let a failed `POST
/api/devices/refresh` throw before the `GET /api/devices` that follows it
ever ran. A provider hiccup, or "Run setup again" with nothing signed in,
rendered an empty list over real, already-tracked devices; Next then read
zero ticked boxes, asked "Track nothing?", and OK posted `device_ids: []` --
untracking everything in one click. These two tests pin the fix from both
directions: a refresh failure that still lets the list load must change
nothing about tracking that was not touched, and a device list that never
loads at all must be a true no-op for Next, the same guarantee Skip already
gives.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _set_completed_at(page, base_url, value):
    return await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _set_last_step(page, base_url, value):
    return await page.request.post(
        base_url + "/api/settings/onboarding.last_step",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _unfinished(page, base_url):
    """Run each test against a never-onboarded install, and always restore
    (see test_setup_wizard_devices.py's own fixture of the same name)."""
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, None)
    try:
        yield
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


def _serve_devices(devices: list[dict]):
    async def handler(route):
        await route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"devices": devices})
        )

    return handler


async def _fail(route):
    await route.fulfill(
        status=500, content_type="application/json", body=json.dumps({"detail": "boom"})
    )


async def _clicked_next_with_dialog_guard(page):
    """Click Next while recording any native confirm() dialog, dismissing it
    so a regression (the old "Track nothing?" prompt) cannot hang the test."""
    dialogs: list[str] = []

    async def dismiss(dialog):
        dialogs.append(dialog.message)
        await dialog.dismiss()

    page.on("dialog", dismiss)
    try:
        await page.click("#fp-wizard-next")
        await page.wait_for_timeout(300)
    finally:
        page.remove_listener("dialog", dismiss)
    return dialogs


async def test_refresh_failure_still_lists_known_devices_and_keeps_their_tracking(
    page, base_url
) -> None:
    """A failed refresh must never blank a list of devices Find+ already
    knows about, and Next must post exactly what is (still) ticked."""
    track_calls: list[dict] = []

    async def track(route):
        track_calls.append(route.request.post_data_json)
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"tracked_count": 1}),
        )

    device = {
        "device_id": "TAG-1",
        "name": "Keys",
        "provider": "google-find-hub",
        "is_tracked": True,
        "label": None,
        "icon": None,
        "color": None,
    }
    await page.route("**/api/devices/refresh", _fail)
    await page.route("**/api/devices/track", track)
    await page.route("**/api/devices", _serve_devices([device]))

    await _set_last_step(page, base_url, "devices")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-devices-list input[data-track]", timeout=15000)

    # Still listed, still ticked, despite the refresh failure.
    boxes = page.locator("#fp-setup-devices-list input[data-track]")
    assert await boxes.count() == 1
    assert await boxes.first.is_checked()
    await page.wait_for_function(
        "() => document.getElementById('fp-setup-devices-error').textContent.length > 0",
        timeout=15000,
    )

    dialogs = await _clicked_next_with_dialog_guard(page)
    assert dialogs == [], "a device that is still ticked must never trigger the empty confirm"
    assert track_calls == [{"device_ids": ["TAG-1"]}], track_calls


async def test_refresh_and_list_failure_next_never_touches_tracking(page, base_url) -> None:
    """When the device list itself never loads (not just the refresh), Next
    must be a true no-op for tracking -- never `device_ids: []`, and never
    even the "Track nothing?" confirm, which is for a list that DID load and
    was deliberately left all unticked.

    Navigates to bare `/`, not `/#/setup`: with a hash already present on the
    very first load, `main()` runs `bootDashboard()` (and its OWN, unrelated
    `GET /api/devices` calls -- devices.js, map.js, places_list.js,
    groups_list.js all read the device list at boot) before ever opening the
    wizard, so a blanket-failing mock would break the dashboard's own boot
    and the wizard would never mount at all. An empty initial hash instead
    takes the redirect path (checkOnboarding() -> the hashchange listener ->
    applyHashRoute()), which skips bootDashboard() entirely -- the same path
    test_fresh_state_redirects_to_setup (test_setup_wizard.py) already uses.
    """
    track_calls: list[dict] = []

    async def track(route):
        track_calls.append(route.request.post_data_json)
        await route.fulfill(status=200, content_type="application/json", body="{}")

    await page.route("**/api/devices/refresh", _fail)
    await page.route("**/api/devices/track", track)
    await page.route("**/api/devices", _fail)

    await _set_last_step(page, base_url, "devices")
    await page.goto(base_url + "/")
    await page.wait_for_function("() => window.location.hash === '#/setup'", timeout=15000)
    await page.wait_for_function(
        "() => document.getElementById('fp-setup-devices-error')?.textContent.length > 0",
        timeout=15000,
    )

    dialogs = await _clicked_next_with_dialog_guard(page)
    assert track_calls == [], "a device list that never loaded must never post a tracking change"
    assert dialogs == [], "no confirm should fire when the list never loaded at all"

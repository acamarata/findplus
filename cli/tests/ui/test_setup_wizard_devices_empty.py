"""Browser tests for the wizard's Devices step with zero known devices
(UAT7-N10).

Before this fix, a bare install's Devices step still asked "Track nothing?"
on Next even though there was nothing to track in the first place, still drew
an orphan "Track" column header over the empty state, and POSTed
`/api/devices/refresh` on every visit regardless of whether a provider was
even signed in -- routes_devices.py always answers that particular case with
a 409, logged to the console on every single load. `refresh()`
(setup_steps/devices.js) now checks `GET /api/auth/status` first (through the
shared `anyProviderSignedIn()`, poll_status.js) and skips the doomed POST once
every provider reports signed out.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from ._signin_helpers import reply, status_body
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
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, None)
    try:
        yield
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def _empty_devices(route):
    await route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"devices": []})
    )


async def _ok(route):
    await route.fulfill(status=200, content_type="application/json", body="{}")


async def test_empty_devices_list_skips_the_refresh_post_when_no_provider_is_signed_in(
    page, base_url
):
    """The refresh POST always 409s with nobody signed in; it must never even
    fire, which is the console-error complaint UAT7-N10 raised."""
    refresh_calls = []

    async def refresh(route):
        refresh_calls.append(route.request.url)
        await route.fulfill(
            status=409, content_type="application/json", body=json.dumps({"detail": "no provider"})
        )

    await page.route("**/api/auth/status", reply(status_body()))  # nobody signed in
    await page.route("**/api/devices/refresh", refresh)
    await page.route("**/api/devices", _empty_devices)

    await _set_last_step(page, base_url, "devices")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-devices-list", timeout=15000)
    await page.wait_for_function(
        "() => document.getElementById('fp-setup-devices-list').textContent.length > 0",
        timeout=15000,
    )

    assert refresh_calls == [], "refresh() must not POST when no provider is signed in"


async def test_refresh_still_posts_when_a_provider_is_signed_in(page, base_url):
    """The gate only skips the POST on a definite "nobody signed in" answer --
    a signed-in provider with zero devices yet (freshly connected) must still
    refresh normally."""
    refresh_calls = []

    async def refresh(route):
        refresh_calls.append(route.request.url)
        await route.fulfill(status=200, content_type="application/json", body="{}")

    await page.route("**/api/auth/status", reply(status_body(google=True)))
    await page.route("**/api/devices/refresh", refresh)
    await page.route("**/api/devices", _empty_devices)

    await _set_last_step(page, base_url, "devices")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-devices-list", timeout=15000)
    await page.wait_for_function(
        "() => document.getElementById('fp-setup-devices-list').textContent.length > 0",
        timeout=15000,
    )

    assert len(refresh_calls) == 1, refresh_calls


async def test_empty_devices_list_has_no_track_header(page, base_url):
    await page.route("**/api/auth/status", reply(status_body()))
    await page.route("**/api/devices/refresh", _ok)
    await page.route("**/api/devices", _empty_devices)

    await _set_last_step(page, base_url, "devices")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-devices-list", timeout=15000)
    await page.wait_for_function(
        "() => document.getElementById('fp-setup-devices-list').textContent.length > 0",
        timeout=15000,
    )

    assert "Track" not in await page.locator("#setup-view").inner_text()


async def test_empty_devices_list_next_has_no_confirm_and_posts_empty_list(page, base_url):
    track_calls = []

    async def track(route):
        track_calls.append(route.request.post_data_json)
        await route.fulfill(status=200, content_type="application/json", body="{}")

    await page.route("**/api/auth/status", reply(status_body()))
    await page.route("**/api/devices/refresh", _ok)
    await page.route("**/api/devices/track", track)
    await page.route("**/api/devices", _empty_devices)

    await _set_last_step(page, base_url, "devices")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-devices-list", timeout=15000)
    await page.wait_for_function(
        "() => document.getElementById('fp-setup-devices-list').textContent.length > 0",
        timeout=15000,
    )

    await page.click("#fp-wizard-next")
    await page.wait_for_timeout(300)
    opened = await page.locator("#fp-confirm-dialog[open]").count() > 0
    assert not opened, "an empty install has nothing to confirm about tracking"
    assert track_calls == [{"device_ids": []}], track_calls

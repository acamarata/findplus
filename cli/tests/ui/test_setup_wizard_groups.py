"""Browser tests for the wizard's Groups step.

Split out of test_setup_wizard_devices.py (2026-09-26, PRI rule-7 size cap):
that file was already sharing Devices and Groups coverage and crossed the
300-line ceiling once UAT6-N18's own tests landed. Duplicate-name coverage
stays in test_setup_wizard_groups_duplicate.py.

`live_server` is session-scoped and shared across this whole `ui/` tree, so
every test here uses the same `_unfinished` autouse fixture to run against a
never-onboarded install and restore the seeded completion afterward.
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
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, None)
    try:
        yield
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


def _device(device_id: str, name: str, *, tracked: bool) -> dict:
    return {
        "device_id": device_id,
        "name": name,
        "provider": "google-find-hub",
        "is_tracked": tracked,
        "label": None,
        "icon": None,
        "color": None,
    }


def _serve_devices(devices: list[dict]):
    async def handler(route):
        await route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"devices": devices})
        )

    return handler


async def test_groups_step_add_with_no_members_blocks_save(page, base_url):
    """UAT U16: the wizard's own Add (separate code path from the dashboard's
    group dialog) used to create a zero-member group silently."""
    calls: list[str] = []

    async def handle_groups(route):
        if route.request.method == "POST":
            calls.append(route.request.url)
            await route.fulfill(status=201, content_type="application/json", body="{}")
        else:
            await route.continue_()

    await page.route("**/api/devices", _serve_devices([_device("TAG-1", "Keys", tracked=True)]))
    await page.route("**/api/groups", handle_groups)

    await _set_last_step(page, base_url, "groups")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-group-name", timeout=15000)

    await page.fill("#fp-setup-group-name", "No Members")
    await page.click("#fp-setup-group-add")

    await page.wait_for_function(
        "() => document.getElementById('fp-setup-group-error')?.textContent.length > 0",
        timeout=15000,
    )
    assert "Select at least one member." in await page.locator("#fp-setup-group-error").inner_text()
    assert calls == []


async def test_groups_step_name_field_has_an_accessible_name(page, base_url):
    """UAT4 N34: the group name field had only a placeholder, which a screen
    reader stops announcing once something is typed into it."""
    await page.route("**/api/devices", _serve_devices([_device("TAG-1", "Keys", tracked=True)]))

    await _set_last_step(page, base_url, "groups")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-group-name", timeout=15000)

    label = await page.get_attribute("#fp-setup-group-name", "aria-label")
    assert label == "Group name"


async def test_groups_step_empty_name_shows_inline_error(page, base_url):
    """UAT6-N18: Add with an empty name used to just return, with nothing on
    screen to say it had even been pressed."""
    calls: list[str] = []

    async def handle_groups(route):
        if route.request.method == "POST":
            calls.append(route.request.url)
        await route.continue_()

    await page.route("**/api/devices", _serve_devices([_device("TAG-1", "Keys", tracked=True)]))
    await page.route("**/api/groups", handle_groups)

    await _set_last_step(page, base_url, "groups")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-group-name", timeout=15000)

    await page.click("#fp-setup-group-add")
    await page.wait_for_function(
        "() => document.getElementById('fp-setup-group-error')?.textContent.length > 0",
        timeout=15000,
    )
    assert "Name is required." in await page.locator("#fp-setup-group-error").inner_text()
    assert calls == []


async def test_groups_step_lead_and_untracked_device_excluded(page, base_url):
    """UAT6-N18: no intro sentence, and the untracked AirTag from the Devices
    step was still offered as a group member."""
    keys = _device("TAG-1", "Keys", tracked=True)
    airtag = _device("TAG-2", "AirTag", tracked=False)
    await page.route("**/api/devices", _serve_devices([keys, airtag]))

    await _set_last_step(page, base_url, "groups")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-group-name", timeout=15000)

    step_text = await page.locator("#setup-view .fp-wizard-step").inner_text()
    assert "group" in step_text.lower()
    members = await page.locator("#fp-setup-group-members .fp-member-row").all_inner_texts()
    assert any("Keys" in m for m in members)
    assert not any("AirTag" in m for m in members)


async def test_groups_step_no_tracked_devices_shows_empty_hint_no_border(page, base_url):
    """UAT6-N18: with nothing tracked, the members box drew as an empty
    bordered strip instead of saying why it was empty."""
    await page.route("**/api/devices", _serve_devices([_device("TAG-1", "AirTag", tracked=False)]))

    await _set_last_step(page, base_url, "groups")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-group-name", timeout=15000)

    members = page.locator("#fp-setup-group-members")
    await members.locator(".fp-tab-hint").wait_for(state="visible")
    assert "fp-setup-group-members-empty" in (await members.get_attribute("class") or "")
    border = await members.evaluate("(el) => getComputedStyle(el).borderStyle")
    assert border == "none", border

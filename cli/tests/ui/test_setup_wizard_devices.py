"""Browser tests for the wizard's Devices and Groups steps.

Split out of test_setup_wizard.py (T1, 2026-09-22, PRI rule-7 size caps):
that file stayed over both the 300-line file cap and the 50-line function
cap once UAT U2/U15/U16 landed their own devices/groups-step coverage.
Everything else (Welcome/Sign-in/App-lock/Done/reload/rerun/banner) stays
in test_setup_wizard.py.

`live_server` is session-scoped and shared across this whole `ui/` tree
(see test_setup_wizard.py's own docstring), so every test here uses the same
`_unfinished` autouse fixture to run against a never-onboarded install and
restore the seeded completion afterward.
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
    """Run each test against a never-onboarded install, and always restore.

    `loop_scope="session"` is mandatory, not tidiness: `page` is driven by the
    one session-scoped loop that owns Chrome (see test_setup_wizard.py's own
    fixture and conftest.py's `browser_session`).
    """
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
    """A page.route() handler factory: GET /api/devices always answers `devices`."""

    async def handler(route):
        await route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"devices": devices})
        )

    return handler


async def _ok(route):
    await route.fulfill(status=200, content_type="application/json", body="{}")


async def test_devices_step_done_count_reflects_what_was_just_tracked(page, base_url):
    """UAT U2: Done's count read the Devices step's pre-track snapshot of
    ctx.state.devices, so ticking every tracker still showed "0 device(s)
    tracked." devices.js's onNext now re-fetches before the transition, and
    done.js renders through plural() so the count also reads grammatically."""
    devices_gets = 0

    async def get_devices(route):
        nonlocal devices_gets
        devices_gets += 1
        # Untracked on the Devices step's own onEnter refresh(); tracked once
        # onNext's POST /api/devices/track has "landed" and re-fetches.
        # UAT4 N29: done.js now reads tracked_count off this same response
        # (the real server always includes it, routes_devices.py), so the
        # mock must too.
        tracked = devices_gets > 1
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "tracked_count": 1 if tracked else 0,
                    "devices": [_device("TAG-1", "Keys", tracked=tracked)],
                }
            ),
        )

    await page.route("**/api/devices/refresh", _ok)
    await page.route("**/api/devices/track", _ok)
    await page.route("**/api/devices", get_devices)

    await _set_last_step(page, base_url, "devices")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-devices-list input[data-track]", timeout=15000)

    await page.check("#fp-setup-devices-list input[data-track]")
    await page.click("#fp-wizard-next")

    # Groups, Places, Notifications, App lock: all optional, skip straight
    # through to Done without touching their own fields.
    for _ in range(4):
        await page.wait_for_selector("#fp-wizard-skip:not([hidden])", timeout=15000)
        await page.click("#fp-wizard-skip")

    await page.wait_for_function(
        "() => document.querySelector('#setup-view h2')?.textContent === \"You're set up\"",
        timeout=15000,
    )
    summary = await page.locator("#setup-view p").first.inner_text()
    assert summary == "1 device tracked."


async def test_devices_step_track_header_default_ticks_and_confirm_on_none(page, base_url) -> None:
    """UAT U15: no "Track" header, every row started unticked even on a
    fresh account, and Next silently tracked nothing with none ticked."""
    await page.route("**/api/devices/refresh", _ok)
    await page.route("**/api/devices/track", _ok)
    keys = _device("TAG-1", "Keys", tracked=False)
    bag = _device("TAG-2", "Bag", tracked=False)
    await page.route("**/api/devices", _serve_devices([keys, bag]))

    await _set_last_step(page, base_url, "devices")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-devices-list input[data-track]", timeout=15000)

    assert "Track" in await page.locator("#setup-view").inner_text()

    boxes = page.locator("#fp-setup-devices-list input[data-track]")
    assert await boxes.count() == 2
    assert await boxes.nth(0).is_checked()
    assert await boxes.nth(1).is_checked()
    assert await boxes.nth(0).get_attribute("aria-label") == "Track Keys"

    await boxes.nth(0).uncheck()
    await boxes.nth(1).uncheck()

    dialogs: list[str] = []

    async def dismiss(dialog):
        dialogs.append(dialog.message)
        await dialog.dismiss()

    page.on("dialog", dismiss)
    try:
        await page.click("#fp-wizard-next")
        await page.wait_for_timeout(300)
        assert dialogs, "Next with nothing ticked must ask to confirm"
        # Declining must not advance past the step.
        assert await page.locator("#fp-setup-devices-list").is_visible()
    finally:
        page.remove_listener("dialog", dismiss)


async def test_devices_step_checkbox_stays_inline_with_name_at_375(page, base_url) -> None:
    """UAT U15: the row's own 5 children tripped the generic mobile rule that
    stacks a .fp-dialog-field with a text input into one column per child,
    leaving the checkbox alone above the device name."""
    await page.route("**/api/devices/refresh", _ok)
    await page.route("**/api/devices", _serve_devices([_device("TAG-1", "Keys", tracked=False)]))
    await page.set_viewport_size({"width": 375, "height": 800})
    try:
        await _set_last_step(page, base_url, "devices")
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("#fp-setup-devices-list input[data-track]", timeout=15000)

        box_box = await page.locator("#fp-setup-devices-list input[data-track]").bounding_box()
        name_box = await page.locator("#fp-setup-devices-list .fp-device-badge").bounding_box()
        assert abs(box_box["y"] - name_box["y"]) < 10, (box_box, name_box)
    finally:
        await page.set_viewport_size({"width": 1280, "height": 900})
        await _set_last_step(page, base_url, None)


async def test_devices_step_label_input_is_not_squeezed_at_375(page, base_url) -> None:
    """UAT N13: `.fp-dialog-field input[type="text"] { flex: 1; min-width: 0; }`
    let the label input shrink to fit whatever was left on the row instead of
    wrapping onto its own line -- "Your name for this tracker" read as
    "Your na" at 375px. It now carries its own flex-basis/min-width, so it
    wraps instead of shrinking, with room to read most of the placeholder."""
    await page.route("**/api/devices/refresh", _ok)
    await page.route(
        "**/api/devices", _serve_devices([_device("TAG-1", "Chipolo ONE Point", tracked=False)])
    )
    await page.set_viewport_size({"width": 375, "height": 800})
    try:
        await _set_last_step(page, base_url, "devices")
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("#fp-setup-devices-list input[data-track]", timeout=15000)

        label = page.locator("#fp-setup-devices-list input[type='text']")
        box = await label.bounding_box()
        assert box["width"] >= 130, box
    finally:
        await page.set_viewport_size({"width": 1280, "height": 900})
        await _set_last_step(page, base_url, None)


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


async def test_groups_step_duplicate_name_shows_inline_error(page, base_url):
    """N45: a duplicate group name's 409 went to ctx.showAlert, which writes
    into #alert inside #app-shell -- hidden for the whole time the wizard is
    open, so nothing appeared on screen and the name silently stayed in the
    box. The step's own #fp-setup-group-error now carries it, announced via
    role="alert" the same way as the members-required message above."""

    async def handle_groups(route):
        if route.request.method == "POST":
            await route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({"detail": "group name 'Pets' already exists"}),
            )
        else:
            await route.continue_()

    await page.route("**/api/devices", _serve_devices([_device("TAG-1", "Keys", tracked=True)]))
    await page.route("**/api/groups", handle_groups)

    await _set_last_step(page, base_url, "groups")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-group-name", timeout=15000)

    await page.fill("#fp-setup-group-name", "Pets")
    await page.check("#fp-setup-group-members input[type='checkbox']")
    await page.click("#fp-setup-group-add")

    error = page.locator("#fp-setup-group-error")
    await page.wait_for_function(
        "() => document.getElementById('fp-setup-group-error')?.textContent.length > 0",
        timeout=15000,
    )
    assert "already exists" in await error.inner_text()
    assert await error.get_attribute("role") == "alert"
    # The name box is untouched, ready for the user to try a different name.
    assert await page.input_value("#fp-setup-group-name") == "Pets"

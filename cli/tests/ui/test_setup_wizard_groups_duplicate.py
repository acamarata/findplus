"""Wizard Groups step: the duplicate-name 409's inline error (UAT5 N45).

Split out of test_setup_wizard_devices.py (T1, 2026-09-23, PRI rule-7
300-line file cap): this file was at the cap and this one test pushed it
over. Shares that file's `_unfinished` autouse fixture (run against a
never-onboarded install, restore the seeded completion afterward) and its
`_device`/`_serve_devices`/`_set_last_step` helpers, copied rather than
imported -- the same pattern test_device_display_name.py already uses for
`_open_devices`.
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


async def test_groups_step_duplicate_name_shows_inline_error(page, base_url):
    """N45: a duplicate group name's 409 went to ctx.showAlert, which writes
    into #alert inside #app-shell -- hidden for the whole time the wizard is
    open, so nothing appeared on screen and the name silently stayed in the
    box. The step's own #fp-setup-group-error now carries it, announced via
    role="alert" the same way as the members-required message."""

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

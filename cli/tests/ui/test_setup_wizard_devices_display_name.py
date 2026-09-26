"""Browser tests for the wizard Devices step's row identity (UAT7-N02).

The row read the raw provider name with no icon at all for a device the
dashboard already shows labelled and badged -- displayName()'s fallback chain
(label, then name, then device_id) and devices.js's own badgeCell() colour
fallback (`d.color || colorFor(d.device_id)`) were never applied here, only
in devices.js, groups_list.js, map.js and timeline.js. Seed
(cli/tests/ui/_seed_script.py): TAG-HOME carries label "Ali's Keys", icon
"lucide:key" and color "#4f8cf7"; its raw provider name is "Home Tag" --
exactly the split test_device_display_name.py already pins for the dashboard's
own device dialog.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")

LABEL = "Ali's Keys"


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
    """Run against a never-onboarded install so the wizard opens on Devices,
    with the seeded devices still real (no /api/devices mock): TAG-HOME's
    label and icon come straight from the shared UI database."""
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, "devices")
    try:
        yield
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def _home_row(page, base_url):
    await page.goto(base_url + "/#/setup")
    checkbox = page.locator('#fp-setup-devices-list [data-device-id="TAG-HOME"]')
    await checkbox.wait_for(state="visible", timeout=15000)
    return page.locator("#fp-setup-devices-list .fp-setup-device-row").filter(
        has=page.locator('[data-device-id="TAG-HOME"]')
    )


async def test_wizard_device_row_shows_the_label_not_the_raw_name(page, base_url):
    row = await _home_row(page, base_url)
    # Two <span> children: the badge, then the name (see _device_row.js).
    name = row.locator("span").nth(1)
    text = await name.inner_text()
    assert text == LABEL, text
    assert "Home Tag" not in text


async def test_wizard_device_row_track_checkbox_aria_label_uses_the_label(page, base_url):
    row = await _home_row(page, base_url)
    checkbox = row.locator('[data-device-id="TAG-HOME"]')
    aria_label = await checkbox.get_attribute("aria-label")
    assert aria_label == f"Track {LABEL}", aria_label


async def test_wizard_device_row_badge_shows_the_seeded_icon(page, base_url):
    """The seeded icon is "lucide:key" (badge.js's appendLucideGlyph draws a
    <use href="#lucide-key">); before the fix the row's own colour had no
    colorFor() fallback either, but every device this test seeds a colour for
    already has one, so this pins the icon half of the finding."""
    row = await _home_row(page, base_url)
    glyph = row.locator(".fp-device-badge use")
    await glyph.wait_for(state="attached", timeout=5000)
    href = await glyph.get_attribute("href")
    assert href == "#lucide-key", href

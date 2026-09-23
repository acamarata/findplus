"""Playwright test for the Devices dialog's request-rate line pluralization
(UAT4 N43). Split out of test_devices_dialog.py at the PRI rule-7 300-line
file cap; `_open_devices` is copied here rather than imported, the same
pattern test_device_display_name.py already uses for this helper.

Seed (cli/tests/ui/conftest.py): 4 devices known, 3 tracked (TAG-HOME,
TAG-AWAY, TAG-STALE). `live_server` is session-scoped and shared with every
other file here; this test only unticks checkboxes in the dialog, never
saves, so the shared seed is untouched.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_devices(page, base_url):
    await page.goto(base_url + "/")
    # main.js wires #btn-devices during an async boot. Clicking before the map
    # is up lands on a button with no listener and the dialog never opens.
    await page.wait_for_selector("#map.leaflet-container")
    await page.wait_for_selector('button[data-tab="places"]')
    await page.click("#btn-devices")
    await page.wait_for_selector("#device-modal:not(.hidden)")
    await page.wait_for_selector(".device-row")


async def test_device_rate_line_is_plural_and_singular(page, base_url):
    """UAT4 N43: "{count} device(s) tracked" never resolved the "(s)" --
    the seed tracks 3 of 4 devices, so the dialog opens on the plural form;
    unticking down to exactly one flips it to the singular one."""
    await _open_devices(page, base_url)
    rate = page.locator("#device-rate")
    await rate.wait_for(state="visible")
    text = await rate.inner_text()
    assert "3 devices tracked" in text
    assert "device(s)" not in text

    await page.uncheck("#chk-TAG-AWAY")
    await page.uncheck("#chk-TAG-STALE")
    text = await rate.inner_text()
    assert "1 device tracked" in text
    assert "device(s)" not in text
    assert "1 devices" not in text

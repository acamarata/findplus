"""The desktop-only parts of the wizard and the Settings dialog.

Purpose    : `window.__findplus_native` is set by the Tauri window's own
             initialization script (R-P2-13) and by nothing else, so the
             browser suite has to stub it to reach either surface. Covers the
             native notification section of the wizard's Notifications step
             (whose button is the only place Find+ prompts for the OS
             permission, R-P2-9) and the `alerts.native_detail` row of the
             Settings dialog (R-P2-7).
Constraints: Same session-scoped `live_server` as every other file here, so
             the one test that clears `onboarding.completed_at` restores it in
             a finally. `window.__TAURI__` is stubbed: nothing native runs.
Ticket     : P2-E11-W4-S1-T7 (extra coverage for the R-P2-9/R-P2-13 gates).
"""

from __future__ import annotations

import json

import pytest

from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")

_NATIVE_STUB = """
window.__findplus_native = true;
window.__TAURI__ = { core: { invoke: async () => "granted" } };
"""


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


async def test_native_section_only_exists_in_the_desktop_build(page, base_url):
    """A plain browser tab never offers a control it cannot deliver."""
    await _set_completed_at(page, base_url, None)
    try:
        await _set_last_step(page, base_url, "notifications")
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("[data-channel='telegram']", timeout=15000)
        assert await page.locator("#fp-setup-enable-notifications").count() == 0
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_native_section_asks_for_permission_on_click(page, base_url):
    """R-P2-9: this button is the one trigger of the OS prompt."""
    await _set_completed_at(page, base_url, None)
    try:
        await _set_last_step(page, base_url, "notifications")
        await page.add_init_script(_NATIVE_STUB)
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("#fp-setup-enable-notifications", timeout=15000)

        section = page.locator("[data-channel='native']")
        # The disclosure renders BEFORE any control for the channel (loop-2 F3).
        notes = await section.locator(".fp-wizard-footnote").count()
        assert notes == 2

        await page.click("#fp-setup-enable-notifications")
        await page.wait_for_function(
            "() => document.querySelector('.fp-setup-permission-status').textContent !== ''",
            timeout=15000,
        )
        status = await section.locator(".fp-setup-permission-status").inner_text()
        assert status == "Notifications are on."
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def _open_settings(page, base_url):
    """Wait for the boot to finish before clicking.

    main() wires the dialog asynchronously (catalog, map, then wireControls),
    so a click that lands on the freshly parsed markup hits a button with no
    handler yet and the modal never opens.
    """
    await page.goto(base_url + "/", wait_until="networkidle")
    await page.wait_for_selector("#btn-settings", timeout=15000)
    await page.wait_for_timeout(1000)
    await page.click("#btn-settings")


async def test_settings_native_detail_row_is_desktop_only(page, base_url):
    await _open_settings(page, base_url)
    await page.wait_for_selector("#setting-poll-interval", timeout=15000)
    assert await page.locator("#setting-native-detail-row").is_hidden()

    await page.add_init_script(_NATIVE_STUB)
    await _open_settings(page, base_url)
    await page.wait_for_selector("#setting-native-detail-row:not([hidden])", timeout=15000)
    note = await page.locator("#setting-native-detail-note").inner_text()
    assert "locked screen" in note

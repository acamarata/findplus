"""Playwright browser tests for Settings dialog error/confirmation messages
(UAT U19): a validation error used to render in the page banner (#alert),
which sits behind the modal backdrop and is never seen while the dialog is
open. showSettingsMessage() now writes into #settings-message inside the
dialog, and the poll interval has its own field-level line (UAT2 U19).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_settings(page, base_url) -> None:
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")
    await page.click("#btn-settings")
    # openSettings() unhides first and fills afterwards; its loadSettings()
    # resets the poll field and clears its error, so wait for the fills.
    await page.wait_for_selector("#settings-modal[data-loaded='true']")


async def test_poll_interval_error_renders_inside_the_dialog(page, base_url):
    """UAT U19 (re-walk): an out-of-range poll interval gets a friendly line
    right beside the field, never config_keys.py's raw validator text in
    #settings-message and never the page banner behind the modal."""
    await _open_settings(page, base_url)
    await page.fill("#setting-poll-interval", "2")
    await page.dispatch_event("#setting-poll-interval", "change")

    await page.wait_for_selector("#setting-poll-interval-error:not(.hidden)")
    field_error = await page.locator("#setting-poll-interval-error").inner_text()
    assert "5 to 1440" in field_error
    invalid = await page.get_attribute("#setting-poll-interval", "aria-invalid")
    assert invalid == "true"

    message = await page.locator("#settings-message").inner_text()
    assert "between 5 and 1440" not in message, "raw validator text leaked into the dialog"
    alert_text = await page.locator("#alert").inner_text()
    assert "5 and 1440" not in alert_text, "the error was ALSO echoed to the page banner"


async def test_pin_mismatch_renders_inside_the_dialog(page, base_url):
    await _open_settings(page, base_url)
    await page.fill("#new-pin", "aaaaaa")
    await page.fill("#confirm-pin", "bbbbbb")
    await page.click("#btn-set-pin")

    await page.wait_for_function(
        "document.getElementById('settings-message').textContent.length > 0"
    )
    message = await page.locator("#settings-message").inner_text()
    assert "do not match" in message
    alert_text = await page.locator("#alert").inner_text()
    assert "do not match" not in alert_text, "the error was ALSO echoed to the page banner"


async def test_reopening_settings_clears_the_previous_message(page, base_url):
    await _open_settings(page, base_url)
    await page.fill("#setting-poll-interval", "2")
    await page.dispatch_event("#setting-poll-interval", "change")
    await page.wait_for_selector("#setting-poll-interval-error:not(.hidden)")

    await page.click("#btn-close-settings")
    # Not wait_for_selector("#settings-modal.hidden", the default "visible"
    # state): a hidden modal is never visible by definition, so that would
    # never resolve. The class is what closeSettings() actually toggles.
    await page.wait_for_function(
        "document.getElementById('settings-modal').classList.contains('hidden')"
    )
    await page.click("#btn-settings")
    await page.wait_for_selector("#settings-modal[data-loaded='true']")
    assert await page.locator("#settings-message").inner_text() == ""
    error = page.locator("#setting-poll-interval-error")
    assert "hidden" in (await error.get_attribute("class") or "")

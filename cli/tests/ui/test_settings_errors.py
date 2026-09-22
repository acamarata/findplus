"""Playwright browser tests for Settings dialog error/confirmation messages
(UAT U19): a validation error used to render in the page banner (#alert),
which sits behind the modal backdrop and is never seen while the dialog is
open. settings.js's showSettingsMessage() now writes into #settings-message,
inside the dialog itself.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_settings(page, base_url) -> None:
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")
    await page.click("#btn-settings")
    await page.wait_for_selector("#settings-modal:not(.hidden)")


async def test_poll_interval_error_renders_inside_the_dialog(page, base_url):
    """config_keys.py rejects anything outside 5-1440 minutes with a plain
    ValueError string; the UAT report quoted this exact message showing in
    the page banner, unreadable behind the modal."""
    await _open_settings(page, base_url)
    await page.fill("#setting-poll-interval", "2")
    await page.dispatch_event("#setting-poll-interval", "change")

    await page.wait_for_function(
        "document.getElementById('settings-message').textContent.length > 0"
    )
    message = await page.locator("#settings-message").inner_text()
    assert "between 5 and 1440" in message

    # The page banner behind the modal (#alert) may legitimately show its own
    # unrelated status text (e.g. "nothing tracked"); the defect U19 reports
    # is THIS message landing there instead of in the dialog.
    alert_text = await page.locator("#alert").inner_text()
    assert "between 5 and 1440" not in alert_text, "the error was ALSO echoed to the page banner"


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
    await page.wait_for_function(
        "document.getElementById('settings-message').textContent.length > 0"
    )

    await page.click("#btn-close-settings")
    # Not wait_for_selector("#settings-modal.hidden", the default "visible"
    # state): a hidden modal is never visible by definition, so that would
    # never resolve. The class is what closeSettings() actually toggles.
    await page.wait_for_function(
        "document.getElementById('settings-modal').classList.contains('hidden')"
    )
    await page.click("#btn-settings")
    await page.wait_for_selector("#settings-modal:not(.hidden)")
    assert await page.locator("#settings-message").inner_text() == ""

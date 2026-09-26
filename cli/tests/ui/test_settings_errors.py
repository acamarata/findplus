"""Playwright browser tests for Settings dialog error/confirmation messages
(UAT U19): a validation error used to render in the page banner (#alert),
which sits behind the modal backdrop and is never seen while the dialog is
open. showSettingsMessage() now writes into #settings-message inside the
dialog, and the poll interval has its own field-level line (UAT2 U19).
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

PIN = "864213"


async def _open_settings(page, base_url) -> None:
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")
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


async def test_a_late_dashboard_boot_keeps_the_poll_interval_error(page, base_url):
    """d120166 regression: bootDashboard()'s loadSettings() landing after
    the user opened Settings and typed re-rendered the polling section,
    which reset the field and hid its error (1 in 5 runs under load). Run
    the boot again with the error on screen -- the same call lock.js's
    unlock makes -- instead of racing the first one, so this is deterministic."""
    await _open_settings(page, base_url)
    await page.fill("#setting-poll-interval", "2")
    await page.dispatch_event("#setting-poll-interval", "change")
    await page.wait_for_selector("#setting-poll-interval-error:not(.hidden)")

    await page.evaluate("import('/static/app/main.js').then((m) => m.bootDashboard(null))")

    assert await page.is_visible("#setting-poll-interval-error")
    assert await page.get_attribute("#setting-poll-interval", "aria-invalid") == "true"
    assert await page.input_value("#setting-poll-interval") == "2"


async def test_pin_mismatch_renders_beside_the_field(page, base_url):
    """UAT3 N21 (re-walk): the mismatch line moved beside New PIN, the same
    field-level convention as the poll interval, instead of #settings-message
    at the top of the dialog. GP-R5-5: the mismatch is about both fields, so
    #confirm-pin carries the same aria-invalid as #new-pin."""
    await _open_settings(page, base_url)
    await page.fill("#new-pin", "aaaaaa")
    await page.fill("#confirm-pin", "bbbbbb")
    await page.click("#btn-set-pin")

    await page.wait_for_selector("#setting-new-pin-error:not(.hidden)")
    field_error = await page.locator("#setting-new-pin-error").inner_text()
    assert "do not match" in field_error
    invalid = await page.get_attribute("#new-pin", "aria-invalid")
    assert invalid == "true"
    confirm_invalid = await page.get_attribute("#confirm-pin", "aria-invalid")
    assert confirm_invalid == "true"

    message = await page.locator("#settings-message").inner_text()
    assert "do not match" not in message, "the error was ALSO echoed to #settings-message"
    alert_text = await page.locator("#alert").inner_text()
    assert "do not match" not in alert_text, "the error was ALSO echoed to the page banner"


async def test_short_pin_error_renders_beside_the_field(page, base_url):
    """UAT3 N21 repro: Settings > App lock, PIN 2468, Set PIN -- the server's
    "PIN must be at least 6 characters." 422 used to land in #settings-message,
    scrolled out of view (the pre-fix U19 pattern)."""
    await _open_settings(page, base_url)
    await page.fill("#new-pin", "2468")
    await page.fill("#confirm-pin", "2468")
    await page.click("#btn-set-pin")

    await page.wait_for_selector("#setting-new-pin-error:not(.hidden)")
    field_error = await page.locator("#setting-new-pin-error").inner_text()
    assert "at least 6" in field_error
    invalid = await page.get_attribute("#new-pin", "aria-invalid")
    assert invalid == "true"

    message = await page.locator("#settings-message").inner_text()
    assert message == "", "the raw validator text leaked into #settings-message"
    alert_text = await page.locator("#alert").inner_text()
    assert "at least 6" not in alert_text, "the error was ALSO echoed to the page banner"


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


async def test_new_pin_and_poll_interval_are_described_by_their_error_line(page, base_url):
    """UAT4 N40: neither field error was tied to its input with
    aria-describedby, so a screen reader on the New PIN or poll interval
    field never heard the rejection rendered right beside it. GP-R5-5:
    #confirm-pin has the same gap (a mismatch is rendered in the same
    #setting-new-pin-error line) -- it needs the same attribute."""
    await _open_settings(page, base_url)
    assert await page.get_attribute("#new-pin", "aria-describedby") == "setting-new-pin-error"
    assert await page.get_attribute("#confirm-pin", "aria-describedby") == "setting-new-pin-error"
    assert (
        await page.get_attribute("#setting-poll-interval", "aria-describedby")
        == "setting-poll-interval-error"
    )


async def _remove_configured_pin_via_ui(page, base_url) -> None:
    """Settings is open, a PIN is configured: remove it through the same
    Remove PIN button/confirm dialog a user would use, not the raw API."""
    await _open_settings(page, base_url)
    await page.wait_for_selector("#lock-is-set:not(.hidden)")
    await page.fill("#current-pin", PIN)
    await page.click("#btn-remove-pin")
    await page.wait_for_selector("#fp-confirm-dialog[open]")
    await page.locator("#fp-confirm-dialog").get_by_role("button", name="Remove").click()
    await page.wait_for_selector("#lock-not-set:not(.hidden)")


async def _clear_pin_if_configured(page, base_url) -> None:
    """Best-effort cleanup: leave the shared server PIN-free for whatever
    test runs next, whether or not a PIN ended up set here."""
    resp = await page.request.get(base_url + "/api/settings")
    if (await resp.json()).get("pin_configured"):
        await page.request.delete(
            base_url + "/api/settings/pin",
            data=json.dumps({"current_pin": PIN}),
            headers={"Content-Type": "application/json"},
        )


async def test_removing_pin_then_a_bad_new_pin_clears_the_top_message(page, base_url):
    """UAT4 N40: "PIN removed. The app no longer locks." stayed at the top of
    the dialog while a too-short PIN typed right afterward showed its own
    rejection beside the New PIN field -- two contradictory messages on
    screen at once. removePin() and setPin() both clear #settings-message
    before doing anything else now, so a fresh attempt never inherits the
    previous one's confirmation.
    """
    set_resp = await page.request.post(
        base_url + "/api/settings/pin",
        data=json.dumps({"new_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert set_resp.ok, await set_resp.text()
    try:
        await _remove_configured_pin_via_ui(page, base_url)
        message = await page.locator("#settings-message").inner_text()
        assert "PIN removed" in message

        await page.fill("#new-pin", "123")
        await page.fill("#confirm-pin", "123")
        await page.click("#btn-set-pin")
        await page.wait_for_selector("#setting-new-pin-error:not(.hidden)")

        assert await page.locator("#settings-message").inner_text() == "", (
            "the stale 'PIN removed' confirmation stayed at the top of the dialog"
        )
        assert (await page.locator("#setting-new-pin-error").inner_text()).strip()
    finally:
        await _clear_pin_if_configured(page, base_url)


async def test_short_pin_never_reaches_the_server(page, base_url):
    """UAT4 N44: a too-short PIN used to reach the server before failing,
    logging a 400 in the console -- test_short_pin_error_renders_beside_the_field
    (above) still exercises that server round trip's visible result, but the
    6-character minimum is now checked client-side first, so the request is
    never sent at all."""
    calls = []

    async def record(route):
        calls.append(route.request.url)
        await route.continue_()

    await page.route("**/api/settings/pin", record)
    await _open_settings(page, base_url)
    await page.fill("#new-pin", "2468")
    await page.fill("#confirm-pin", "2468")
    await page.click("#btn-set-pin")

    await page.wait_for_selector("#setting-new-pin-error:not(.hidden)")
    assert "at least 6" in await page.locator("#setting-new-pin-error").inner_text()
    assert calls == [], "a too-short PIN must never reach the server"

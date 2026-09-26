"""Browser tests for the add/edit-rule dialog's channel picker (UAT U11/U12,
UAT2 U11). Split out of test_alerts_rules.py at the PRI rule-7 300-line file
cap.

Seed data (cli/tests/ui/conftest.py): device "TAG-HOME" ("Home Tag"), reused
here for the add-rule dialog. `open_alerts_tab()` is shared across every
test_alerts_* file via conftest.py.
"""

from __future__ import annotations

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_fresh_add_rule_dialog(page):
    """Open Add rule and wait for the real (connected-channels) render pass,
    not the placeholder one openRuleDialog() shows before it -- webhook is
    always connected wherever this helper is used below."""
    await page.click("#fp-add-rule-btn")
    await page.wait_for_selector("#fp-add-rule-dialog[open]")
    await page.wait_for_function(
        "document.querySelector('#fp-rule-channels input[data-channel=webhook]')?.checked === true"
    )


async def _checked_channels(page) -> list[str]:
    return sorted(
        await page.eval_on_selector_all(
            "#fp-rule-channels input[type=checkbox]:checked",
            "els => els.map((el) => el.dataset.channel)",
        )
    )


async def test_reopening_add_rule_never_inherits_the_previous_rules_ticks(page, base_url):
    """UAT U12/UAT2 U11: rule 1 additionally ticks telegram (unconnected, but
    still tickable per U11's own test below); rule 2's dialog must reopen
    with its own fresh default, never carrying telegram's tick over from
    whatever the previous save left in the DOM.

    The default itself is no longer a hardcoded channel (UAT2 U11 killed
    that) -- it is whatever alerts_rule_dialog.js resolves as "connected" at
    open time, which this suite's session-shared DB does not pin. Capturing
    it fresh on the FIRST open (`baseline`) and asserting the second open
    matches it again is what actually proves "no carryover", independent of
    exactly which channels happen to be connected when this test runs.
    Webhook is connected via a plain PUT so `baseline` is never empty (an
    empty baseline would make an empty "no carryover" trivially true).
    """
    put_resp = await page.request.put(
        base_url + "/api/alerts/channels/webhook",
        data='{"url": "https://example.com/hook"}',
        headers={"Content-Type": "application/json"},
    )
    assert put_resp.ok, await put_resp.text()
    clear_resp = await page.request.delete(base_url + "/api/alerts/channels/telegram")
    assert clear_resp.ok, await clear_resp.text()
    try:
        await open_alerts_tab(page, base_url)
        await _open_fresh_add_rule_dialog(page)
        baseline = await _checked_channels(page)
        assert "webhook" in baseline, f"webhook is connected, must default-tick: {baseline}"
        assert "telegram" not in baseline, f"telegram is disconnected, must not: {baseline}"

        await page.fill("#fp-rule-name", "U12 rule 1")
        await page.select_option("#fp-rule-device", label="Ali's Keys")
        await page.check("#fp-rule-channels input[data-channel=telegram]")
        await page.click("#fp-rule-save")
        await page.wait_for_function("() => !document.getElementById('fp-add-rule-dialog').open")

        await _open_fresh_add_rule_dialog(page)
        checked = await _checked_channels(page)
        assert checked == baseline, f"leftover ticks from the previous rule: {checked}"
    finally:
        await page.request.delete(base_url + "/api/alerts/channels/webhook")


async def test_add_rule_dialog_flags_an_unconnected_channel(page, base_url):
    """UAT U11: a channel with no stored credentials is flagged in the
    dialog -- dimmed, and its label carries a "(not connected)" suffix
    (channelLabels() in alerts_rule_channels.js) -- but still tickable: a
    fresh install with nothing connected yet must still be able to create its
    first rule (channels is a required, non-empty field server-side).

    Telegram is explicitly cleared first (idempotent DELETE) rather than
    assumed unconnected from a clean DB: test_alerts_telegram.py in the same
    session may have connected it before this file's tests run.
    """
    clear_resp = await page.request.delete(base_url + "/api/alerts/channels/telegram")
    assert clear_resp.ok, await clear_resp.text()
    await open_alerts_tab(page, base_url)
    await page.click("#fp-add-rule-btn")
    await page.wait_for_selector("#fp-add-rule-dialog[open]")
    telegram_option = page.locator("#fp-rule-channels label:has(input[data-channel=telegram])")
    await page.wait_for_function(
        """document.querySelector('#fp-rule-channels label:has(input[data-channel=telegram])')
            .classList.contains('fp-channel-picker-option--disconnected')"""
    )
    telegram = page.locator("#fp-rule-channels input[data-channel=telegram]")
    assert await telegram.is_disabled() is False, "still tickable -- U11 flags, it does not block"
    assert "not connected" in await telegram_option.inner_text()


async def test_add_rule_dialog_defaults_to_only_connected_channels(page, base_url):
    """UAT2 U11: the dialog used to always start with telegram ticked, so a
    user ticking WhatsApp only (leaving the stale telegram tick in place)
    saved "telegram, whatsapp" with no warning. A fresh install where
    whatsapp is the only connected channel must open with whatsapp alone
    ticked, nothing else.
    """
    for channel in ("telegram", "webhook"):
        resp = await page.request.delete(f"{base_url}/api/alerts/channels/{channel}")
        assert resp.ok, await resp.text()
    put_resp = await page.request.put(
        base_url + "/api/alerts/channels/whatsapp",
        data='{"phone": "+34123123123", "apikey": "1234567890"}',
        headers={"Content-Type": "application/json"},
    )
    assert put_resp.ok, await put_resp.text()
    try:
        await open_alerts_tab(page, base_url)
        await page.click("#fp-add-rule-btn")
        await page.wait_for_selector("#fp-add-rule-dialog[open]")
        await page.wait_for_function(
            "document.querySelector('#fp-rule-channels input[data-channel=whatsapp]')"
            "?.checked === true"
        )
        checked = await _checked_channels(page)
        assert "telegram" not in checked, f"telegram is disconnected: {checked}"
        assert "webhook" not in checked, f"webhook is disconnected: {checked}"
    finally:
        await page.request.delete(base_url + "/api/alerts/channels/whatsapp")


async def _connected_webhook(page, base_url):
    """webhook connected, PUT then open the alerts tab -- _open_fresh_add_rule_
    dialog() below waits for webhook to render ticked, so every caller needs
    at least one connected channel regardless of what it is actually testing."""
    put_resp = await page.request.put(
        base_url + "/api/alerts/channels/webhook",
        data='{"url": "https://example.com/hook"}',
        headers={"Content-Type": "application/json"},
    )
    assert put_resp.ok, await put_resp.text()
    await open_alerts_tab(page, base_url)


async def test_native_channel_is_never_offered_in_a_plain_browser(page, base_url):
    """UAT6 N05: "Desktop notification" used to be offered (and, since native
    needs no credentials, pre-ticked) off nothing but a macOS platform sniff
    -- true on any Mac, including this very Playwright tab. It is gated on
    window.__findplus_native now (set only by the Tauri window), which a
    plain browser tab never sets."""
    try:
        await _connected_webhook(page, base_url)
        await _open_fresh_add_rule_dialog(page)
        count = await page.locator("#fp-rule-channels input[data-channel=native]").count()
        assert count == 0, "native offered in a plain browser tab"
    finally:
        await page.request.delete(base_url + "/api/alerts/channels/webhook")


async def test_native_channel_is_offered_inside_the_native_app(page, base_url):
    """The other half of the same gate: window.__findplus_native set (as the
    Tauri shell's own init script does) must still offer it."""
    try:
        await page.add_init_script("window.__findplus_native = true;")
        await _connected_webhook(page, base_url)
        await _open_fresh_add_rule_dialog(page)
        native = page.locator("#fp-rule-channels input[data-channel=native]")
        assert await native.count() == 1
        assert await native.is_checked() is True, "native has no credentials, always defaults on"
    finally:
        await page.request.delete(base_url + "/api/alerts/channels/webhook")

"""Playwright browser tests for the add-rule dialog's client-side validation
(UAT6 N05, major): Save with nothing filled in used to create a live rule
with an empty name, targeting whichever device sorted first (the untracked
AirTag in this suite's seed data), and whatever channel a plain browser
happened to preselect.

`open_alerts_tab()` and the webhook-connect helper pattern are shared with
test_alerts_rule_channels.py; split into its own file (rather than growing
test_alerts_rules.py, already near the PRI rule-7 300-line cap) since this
is a distinct concern -- the dialog's own required-field guards, not the
rules table or the channel picker's connected/disconnected state.
"""

from __future__ import annotations

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_dialog_with_a_connected_channel(page, base_url):
    """Add rule with webhook connected, so a channel is always available to
    tick -- these tests are about name/target/event validation, not about
    UAT2 U11's connected-channel guard (test_alerts_rule_channels.py's own
    job). Returns nothing; caller is responsible for the DELETE cleanup."""
    put_resp = await page.request.put(
        base_url + "/api/alerts/channels/webhook",
        data='{"url": "https://example.com/hook"}',
        headers={"Content-Type": "application/json"},
    )
    assert put_resp.ok, await put_resp.text()
    await open_alerts_tab(page, base_url)
    await page.click("#fp-add-rule-btn")
    await page.wait_for_selector("#fp-add-rule-dialog[open]")
    await page.wait_for_function(
        "document.querySelector('#fp-rule-channels input[data-channel=webhook]')?.checked === true"
    )


async def test_add_rule_requires_a_name(page, base_url):
    """Save with an empty name must refuse client-side (the browser's own
    required-field message) rather than POST a nameless rule."""
    try:
        await _open_dialog_with_a_connected_channel(page, base_url)
        await page.select_option("#fp-rule-device", label="Ali's Keys")
        # ruleFormIsValid()'s reportValidity() call runs synchronously at the
        # very top of saveRule(), before any await -- by the time click()
        # resolves (Playwright waits for the dispatched event to finish
        # running), the check has already happened; no arbitrary wait needed.
        await page.click("#fp-rule-save")
        assert await page.is_visible("#fp-add-rule-dialog[open]"), "saved with no name"
        assert not await page.locator("#fp-rule-name").evaluate("(el) => el.validity.valid")
    finally:
        await page.request.delete(base_url + "/api/alerts/channels/webhook")


async def test_add_rule_device_select_starts_on_choose_a_device(page, base_url):
    """UAT6 N05: a blank placeholder leads the list -- opening the dialog
    must never silently default to whichever device sorts first."""
    try:
        await _open_dialog_with_a_connected_channel(page, base_url)
        selected = await page.locator("#fp-rule-device").input_value()
        assert selected == "", f"device pre-selected: {selected!r}"
        text = await page.locator("#fp-rule-device option:checked").text_content()
        assert "Choose" in text
    finally:
        await page.request.delete(base_url + "/api/alerts/channels/webhook")


async def test_untracked_device_sorts_after_tracked_and_is_labelled(page, base_url):
    """TAG-AIR ("AirTag") is untracked in this suite's seed data -- it must
    render after every tracked device, with a suffix marking it as such,
    never indistinguishable from a real target (UAT6 N05)."""
    try:
        await _open_dialog_with_a_connected_channel(page, base_url)
        options = await page.locator("#fp-rule-device option").all_text_contents()
        air_index = next(i for i, o in enumerate(options) if "AirTag" in o)
        home_index = next(i for i, o in enumerate(options) if "Ali's Keys" in o)
        assert home_index < air_index, options
        assert "not polled" in options[air_index]
    finally:
        await page.request.delete(base_url + "/api/alerts/channels/webhook")


async def test_add_rule_requires_at_least_one_event(page, base_url):
    """Neither On enter nor On exit ticked is a rule that can never fire."""
    try:
        await _open_dialog_with_a_connected_channel(page, base_url)
        await page.fill("#fp-rule-name", "N05 no-event rule")
        await page.select_option("#fp-rule-device", label="Ali's Keys")
        await page.uncheck("#fp-rule-on-enter")
        await page.click("#fp-rule-save")
        await page.wait_for_function(
            "document.getElementById('fp-rule-error').textContent.length > 0"
        )
        error = await page.locator("#fp-rule-error").inner_text()
        assert "enter" in error.lower() or "exit" in error.lower(), error
        assert await page.is_visible("#fp-add-rule-dialog[open]")
    finally:
        await page.request.delete(base_url + "/api/alerts/channels/webhook")


async def test_add_rule_requires_at_least_one_channel(page, base_url):
    """Every channel unticked is a rule with nowhere to deliver to."""
    try:
        await _open_dialog_with_a_connected_channel(page, base_url)
        await page.fill("#fp-rule-name", "N05 no-channel rule")
        await page.select_option("#fp-rule-device", label="Ali's Keys")
        await page.uncheck("#fp-rule-channels input[data-channel=webhook]")
        await page.click("#fp-rule-save")
        await page.wait_for_function(
            "document.getElementById('fp-rule-error').textContent.length > 0"
        )
        error = await page.locator("#fp-rule-error").inner_text()
        assert "channel" in error.lower(), error
        assert await page.is_visible("#fp-add-rule-dialog[open]")
    finally:
        await page.request.delete(base_url + "/api/alerts/channels/webhook")

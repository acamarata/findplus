"""Browser tests for the wizard's Notifications and Places steps
(R-P2-28 points 3 and 5). Split from test_setup_wizard_layout.py (E13 stage 2,
size cap). The sign-in step's Chrome-missing notice tests moved on to
test_setup_wizard_signin_chrome.py (2026-09-26, same cap).
"""

from __future__ import annotations

import json

import pytest

from findplus.honesty import ALERTS_LATENCY, WHATSAPP_RELAY, WHATSAPP_SETUP

from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")


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


async def _open_step(page, base_url, step):
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, step)
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)


def _make_save_route(sink: dict):
    async def save_route(route):
        sink["body"] = json.loads(route.request.post_data)
        # Real shape: PUT returns _channels_response(), which carries the
        # masked phone, never the plaintext one just PUT (loop2 B5).
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"whatsapp": {"configured": True, "phone_masked": "+34… masked"}}),
        )

    return save_route


def _make_test_route(sink: dict):
    async def test_route(route):
        sink["body"] = json.loads(route.request.post_data)
        await route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"status": "sent"})
        )

    return test_route


async def test_notifications_step_whatsapp_save_and_test(page, base_url):
    """R-P2-28 point 3 / F4: WhatsApp gets inline phone/API-key/Save/Test,
    exactly like Telegram, instead of only a "configure later" link."""
    saved, tested = {}, {}
    try:
        await page.route("**/api/alerts/channels/whatsapp", _make_save_route(saved))
        await page.route("**/api/alerts/test", _make_test_route(tested))
        await _open_step(page, base_url, "notifications")
        await page.wait_for_selector("[data-channel='whatsapp']", timeout=15000)

        assert await page.locator("#fp-setup-wa-phone").count() == 1
        assert await page.locator("#fp-setup-wa-apikey").count() == 1

        # T0 addendum B3: both honesty sentences render above the fields.
        section_text = await page.locator("[data-channel='whatsapp']").inner_text()
        assert WHATSAPP_RELAY in section_text
        assert WHATSAPP_SETUP in section_text

        await page.fill("#fp-setup-wa-phone", "+34999888777")
        await page.fill("#fp-setup-wa-apikey", "wizard-test-key")
        await page.click("#fp-setup-wa-save")
        await page.wait_for_timeout(300)
        assert saved["body"] == {"phone": "+34999888777", "apikey": "wizard-test-key"}

        # loop2 B5: the status line shows the PUT response's masked phone,
        # never the plaintext value just typed -- PII per R-P2-27.6.
        status_text = await page.locator("#fp-setup-wa-phone").evaluate(
            "(el) => el.closest('[data-channel]').querySelector('.modal-note').textContent"
        )
        assert "+34… masked" in status_text
        assert "+34999888777" not in status_text

        await page.click("#fp-setup-wa-test")
        await page.wait_for_timeout(200)
        assert tested["body"] == {"channel": "whatsapp"}

        # UAT6-N33: Webhook now offers a button, not a link (a plain sentence
        # explains why: following the old link left the wizard unfinished).
        assert await page.locator("[data-channel='webhook'] a").count() == 0
        button = page.get_by_role("button", name="Finish setup and open Alerts")
        assert await button.count() == 1
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_webhook_configure_later_finishes_setup_and_opens_alerts_tab(page, base_url):
    """UAT6-N33: the old link left the wizard "unfinished" (no completed_at
    stamp), so the next load showed the resume banner over a webhook the user
    had just gone to set up. The button finishes setup, then opens Alerts."""
    try:
        await _open_step(page, base_url, "notifications")
        button = page.get_by_role("button", name="Finish setup and open Alerts")
        await button.click()

        await page.wait_for_function(
            "() => document.getElementById('setup-view').hidden === true", timeout=15000
        )
        assert await page.locator("#app-shell").is_visible()
        assert await page.locator("#tab-alerts").is_hidden() is False
        await page.wait_for_selector("#fp-webhook-section", state="visible", timeout=15000)
        # scrollIntoView({block: "start"}) puts the section's top at the
        # viewport's top edge; a sub-pixel rounding wobble is expected, a
        # section still scrolled well below the fold is the regression.
        top = await page.locator("#fp-webhook-section").evaluate(
            "(el) => el.getBoundingClientRect().top"
        )
        assert -1 <= top <= 50, top

        settings = await (await page.request.get(base_url + "/api/settings")).json()
        assert settings["onboarding.completed_at"] is not None
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_places_step_hides_the_observed_path_disclaimer(page, base_url):
    """R-P2-28 point 5 / F3: a first-run, near-empty map has no observed path
    for the dashboard's disclaimer to describe."""
    try:
        await _open_step(page, base_url, "places")
        await page.wait_for_selector("#fp-setup-map-host #map", timeout=15000)
        assert await page.locator("#path-disclaimer").is_hidden()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_places_step_restores_the_disclaimer_on_leaving(page, base_url):
    try:
        await _open_step(page, base_url, "places")
        await page.wait_for_selector("#fp-setup-map-host #map", timeout=15000)
        await page.evaluate("() => { window.location.hash = ''; }")
        await page.wait_for_function(
            "() => document.getElementById('setup-view').hidden === true", timeout=15000
        )
        assert await page.locator("#path-disclaimer").is_visible()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_notifications_step_latency_honesty_shown_once(page, base_url):
    """UAT U17: alerts_latency appeared once under Telegram and again,
    verbatim, under Webhook -- a copy-paste-looking duplicate. It describes
    both (network-delivered) channels alike, so it now renders once, above
    them, instead of once per channel."""
    try:
        await _open_step(page, base_url, "notifications")
        await page.wait_for_selector("[data-channel='telegram']", timeout=15000)
        step_text = await page.locator("#setup-view .fp-wizard-step").inner_text()
        assert step_text.count(ALERTS_LATENCY) == 1, step_text
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_notifications_step_token_field_is_not_squeezed_against_connect(page, base_url):
    """UAT U17: the token input's browser-default ~20-character width cut
    "Bot token from @BotFather" down to "...@BotFath" flush against Connect."""
    try:
        await _open_step(page, base_url, "notifications")
        token = page.locator("#fp-setup-tg-token")
        # A specific id, not "[data-channel='telegram'] button": the Targets
        # field's own Save/Find-chat-IDs buttons (multi-target Telegram
        # support) made that selector match more than one button.
        connect = page.locator("#fp-setup-tg-connect")
        await token.wait_for(state="visible", timeout=15000)
        token_box = await token.bounding_box()
        connect_box = await connect.bounding_box()
        assert token_box["width"] >= 190, token_box
        assert connect_box["x"] - (token_box["x"] + token_box["width"]) >= 4
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_notifications_step_telegram_help_lines(page, base_url):
    """T0 addendum B6: where the token comes from, and how Find+ finds the
    chat id — the same two things `findplus alerts telegram-setup` explains."""
    try:
        await _open_step(page, base_url, "notifications")
        await page.wait_for_selector("[data-channel='telegram']", timeout=15000)
        section_text = await page.locator("[data-channel='telegram']").inner_text()
        assert "BotFather" in section_text
        assert "chat id" in section_text
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)

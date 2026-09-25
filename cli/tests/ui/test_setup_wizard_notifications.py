"""Browser tests for the wizard's Notifications, Places and Sign-in steps
(R-P2-28 points 3 and 5, plus the T0 sign-in addenda). Split from
test_setup_wizard_layout.py (E13 stage 2, size cap).
"""

from __future__ import annotations

import json

import pytest

from findplus.honesty import ALERTS_LATENCY, CHROME_REQUIRED, WHATSAPP_RELAY, WHATSAPP_SETUP

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

        # Webhook still only offers the "configure later" link, styled with
        # the app's link token rather than the browser default blue (F5).
        link = page.locator("[data-channel='webhook'] a")
        color = await link.evaluate("(el) => getComputedStyle(el).color")
        assert color not in ("rgb(0, 0, 238)", ""), color
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_webhook_configure_later_opens_alerts_tab_webhook_section(page, base_url):
    """UAT U17: the link used to point at "#settings", a dead end -- webhook
    setup lives in the Alerts tab, not Settings."""
    try:
        await _open_step(page, base_url, "notifications")
        link = page.locator("[data-channel='webhook'] a")
        assert await link.get_attribute("href") == "#alerts-webhook"
        await link.click()

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


async def test_signin_step_shows_chrome_notice_before_any_click(page, base_url):
    """T0 addendum B5: GET /api/auth/status's `needs: ["chrome"]` (already
    computed by providers/auth_status.py) is read on entry, not only after a
    failed click, and the Google button is disabled while it applies."""

    async def status_route(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "providers": [
                        {
                            "id": "google-find-hub",
                            "signed_in": False,
                            "account": None,
                            "needs": ["chrome"],
                        }
                    ]
                }
            ),
        )

    try:
        await page.route("**/api/auth/status", status_route)
        await _open_step(page, base_url, "signin")
        await page.wait_for_selector("#fp-setup-chrome-notice:not([hidden])", timeout=15000)
        assert await page.locator("#fp-setup-chrome-notice").inner_text() == CHROME_REQUIRED
        assert await page.get_by_role("button", name="Connect Google Find Hub").is_disabled()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_signin_step_maps_a_400_to_the_honesty_sentence_not_raw_text(page, base_url):
    """T0 addendum B5: the route's only 400 is ChromeNotFoundError, but this
    never trusts the thrown message's text — it renders the live notice."""

    async def start_route(route):
        # Deliberately NOT honesty.CHROME_REQUIRED's text, to prove the UI
        # does not just echo whatever the 400 body happens to say.
        await route.fulfill(
            status=400,
            content_type="application/json",
            body=json.dumps({"detail": "ChromeNotFoundError: no chrome binary on PATH"}),
        )

    try:
        await _open_step(page, base_url, "signin")
        await page.route("**/api/auth/google/start", start_route)
        await page.get_by_role("button", name="Connect Google Find Hub").click()
        await page.wait_for_selector("#fp-setup-chrome-notice:not([hidden])", timeout=15000)
        notice = await page.locator("#fp-setup-chrome-notice").inner_text()
        assert notice == CHROME_REQUIRED
        assert "ChromeNotFoundError" not in notice
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_signin_step_clears_status_line_on_chrome_missing_400(page, base_url):
    """loop2 B1: the status line must not keep reading "Starting Chrome..."
    once the Chrome-missing notice is showing -- that pairs a "please wait"
    message with a "this cannot proceed" one, a contradictory UI state."""

    async def start_route(route):
        await route.fulfill(
            status=400,
            content_type="application/json",
            body=json.dumps({"detail": "ChromeNotFoundError: no chrome binary on PATH"}),
        )

    try:
        await _open_step(page, base_url, "signin")
        await page.route("**/api/auth/google/start", start_route)
        await page.get_by_role("button", name="Connect Google Find Hub").click()
        await page.wait_for_selector("#fp-setup-chrome-notice:not([hidden])", timeout=15000)
        # The in-progress line (E14: one per card) is gone, not left reading
        # "Opening Chrome..." beside a notice that says Chrome is missing.
        assert await page.locator("#fp-setup-google-progress").is_hidden()
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

"""Browser tests for the Notifications step's field labels and copy sizing
(UAT7-N11).

Bot token, targets, phone and API key each had a placeholder as their only
name -- gone the moment a value is typed, so axe's `label` rule and a screen
reader alike got nothing. Each field now sits in a `.fp-signin-field` with a
real, always-visible `<label for>` (the sign-in step's own pattern). The
targets field also gets its own, shorter wizard-only placeholder: the shared
`alerts.telegramTargetsPlaceholder` clipped to "...separated by" at 375px.
The webhook channel's "configure later" sentence had no class and inherited
the 14px body default while every other notice in this step is the 12px
`.fp-wizard-footnote`.
"""

from __future__ import annotations

import json

import pytest

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


def _channels_body(*, telegram_configured: bool = False, whatsapp_configured: bool = False):
    return json.dumps(
        {
            "telegram": {"configured": telegram_configured, "targets": ""},
            "webhook": {"configured": False},
            "whatsapp": {"configured": whatsapp_configured},
        }
    )


async def _open_notifications_step(page, base_url, **channel_flags):
    async def channels(route):
        await route.fulfill(
            status=200, content_type="application/json", body=_channels_body(**channel_flags)
        )

    await page.route("**/api/alerts/channels", channels)
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, "notifications")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("[data-channel='telegram']", timeout=15000)


async def _restore(page, base_url):
    await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
    await _set_last_step(page, base_url, None)


async def _labeled_input(page, input_id, expected_text):
    label = page.locator(f'label[for="{input_id}"]')
    await label.wait_for(state="visible", timeout=10000)
    assert await label.inner_text() == expected_text, input_id
    assert await page.locator(f"#{input_id}").get_attribute("id") == input_id


async def test_telegram_token_field_has_a_visible_label(page, base_url):
    try:
        await _open_notifications_step(page, base_url)
        await _labeled_input(page, "fp-setup-tg-token", "Telegram bot token")
    finally:
        await _restore(page, base_url)


async def test_telegram_targets_field_has_a_visible_label_and_a_shorter_placeholder(page, base_url):
    try:
        await _open_notifications_step(page, base_url, telegram_configured=True)
        await _labeled_input(page, "fp-setup-tg-targets", "Targets")
        placeholder = await page.locator("#fp-setup-tg-targets").get_attribute("placeholder")
        assert placeholder == "Chat IDs or @usernames", placeholder
        # UAT7-N11: this is a DIFFERENT key from the Alerts tab's own
        # alerts.telegramTargetsPlaceholder -- shortening the wizard's copy
        # must never shorten (or touch) the wider Alerts tab field.
        assert len(placeholder) < len("Chat ID, @username, or several separated by commas")
    finally:
        await _restore(page, base_url)


async def test_whatsapp_phone_and_apikey_fields_have_visible_labels(page, base_url):
    try:
        await _open_notifications_step(page, base_url)
        await page.wait_for_selector("[data-channel='whatsapp']")
        await _labeled_input(page, "fp-setup-wa-phone", "Phone")
        await _labeled_input(page, "fp-setup-wa-apikey", "API key")
    finally:
        await _restore(page, base_url)


async def test_webhook_configure_later_sentence_matches_footnote_size(page, base_url):
    try:
        await _open_notifications_step(page, base_url)
        webhook_note = page.locator('[data-channel="webhook"] > p').first
        await webhook_note.wait_for(state="visible", timeout=10000)
        size = await webhook_note.evaluate("(el) => getComputedStyle(el).fontSize")
        assert size == "12px", size
    finally:
        await _restore(page, base_url)


async def test_targets_field_at_375_shows_the_whole_placeholder(page, base_url):
    """UAT7-N11: the old shared placeholder clipped to "...separated by" at
    375px; the shorter wizard-only one must fit without being cut off."""
    await page.set_viewport_size({"width": 375, "height": 800})
    try:
        await _open_notifications_step(page, base_url, telegram_configured=True)
        field = page.locator("#fp-setup-tg-targets")
        await field.wait_for(state="visible", timeout=10000)
        overflow = await field.evaluate("(el) => el.scrollWidth - el.clientWidth")
        assert overflow <= 2, overflow
    finally:
        await page.set_viewport_size({"width": 1280, "height": 900})
        await _restore(page, base_url)

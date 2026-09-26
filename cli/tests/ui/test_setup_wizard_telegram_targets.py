"""Browser tests for the setup wizard's Notifications step: the Telegram
Targets field and "Find chat IDs" helper (multi-target Telegram support).
Split from test_setup_wizard_notifications.py so this ticket's tests have
their own file rather than growing a file shared with the wizard-visuals
work happening in the same repo.

UAT6-N15 (2026-09-26): the targets field, Save and Find chat IDs used to be
live before a bot was even connected, answering "Telegram not configured" in
plain grey text on a click. They are now disabled until GET /api/alerts/
channels reports telegram.configured -- every test in this file that
exercises the targets themselves mocks that route as already configured, the
same way a real "come back after connecting" session would see it; the
disabled-by-default and enable-on-connect behaviour gets its own tests below.
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


def _channels_body(*, configured: bool, targets: str = ""):
    return json.dumps(
        {
            "telegram": {"configured": configured, "targets": targets},
            "webhook": {"configured": False},
            "whatsapp": {"configured": False},
        }
    )


async def _open_notifications_step(page, base_url, *, telegram_configured=True):
    async def channels(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=_channels_body(configured=telegram_configured),
        )

    await page.route("**/api/alerts/channels", channels)
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, "notifications")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("[data-channel='telegram']", timeout=15000)


async def test_wizard_has_a_targets_field_and_help_text(page, base_url):
    try:
        await _open_notifications_step(page, base_url)
        assert await page.locator("#fp-setup-tg-targets").count() == 1
        section_text = await page.locator("[data-channel='telegram']").inner_text()
        assert "comma" in section_text.lower()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_wizard_save_targets_puts_the_field_value(page, base_url):
    saved = {}

    async def targets_route(route):
        saved["body"] = json.loads(route.request.post_data)
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"telegram": {"configured": True, "targets": "123,456"}}),
        )

    try:
        await page.route("**/api/alerts/channels/telegram/targets", targets_route)
        await _open_notifications_step(page, base_url)
        await page.fill("#fp-setup-tg-targets", "123, 456")
        await page.click("#fp-setup-tg-save-targets")
        await page.wait_for_timeout(300)
        assert saved["body"] == {"targets": "123, 456"}
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_wizard_find_chat_ids_adds_to_the_targets_field(page, base_url):
    async def updates_route(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"chats": [{"id": "999", "type": "private", "title": "Bob", "username": "bob"}]}
            ),
        )

    try:
        await page.route("**/api/alerts/channels/telegram/updates", updates_route)
        await _open_notifications_step(page, base_url)
        await page.click("#fp-setup-tg-find-chats")
        await page.wait_for_selector("#fp-setup-tg-chats-list li")
        await page.locator("#fp-setup-tg-chats-list li", has_text="Bob").locator("button").click()
        value = await page.locator("#fp-setup-tg-targets").input_value()
        assert "999" in value
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_wizard_find_chat_ids_no_updates_yet(page, base_url):
    async def updates_route(route):
        await route.fulfill(status=200, content_type="application/json", body='{"chats": []}')

    try:
        await page.route("**/api/alerts/channels/telegram/updates", updates_route)
        await _open_notifications_step(page, base_url)
        await page.click("#fp-setup-tg-find-chats")
        await page.wait_for_function(
            "document.getElementById('fp-setup-tg-targets-status').textContent"
            ".toLowerCase().includes('message')"
        )
        assert await page.locator("#fp-setup-tg-chats-list").is_hidden()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_targets_are_disabled_until_a_bot_is_connected(page, base_url):
    """UAT6-N15: before this fix these three controls were live from the
    moment the section rendered, whatever GET /api/alerts/channels said."""
    try:
        await _open_notifications_step(page, base_url, telegram_configured=False)
        assert not await page.locator("#fp-setup-tg-targets").is_enabled()
        assert not await page.locator("#fp-setup-tg-save-targets").is_enabled()
        assert not await page.locator("#fp-setup-tg-find-chats").is_enabled()
        section_text = await page.locator("[data-channel='telegram']").inner_text()
        assert "connect the bot" in section_text.lower(), section_text
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_targets_enable_the_moment_the_bot_connects(page, base_url):
    """UAT6-N15: connecting a bot THIS session must free the targets
    controls immediately, not only after the wizard re-renders."""

    async def setup_route(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"chat_title": "Family"}),
        )

    try:
        await page.route("**/api/alerts/channels/telegram/setup*", setup_route)
        await _open_notifications_step(page, base_url, telegram_configured=False)
        await page.wait_for_selector("#fp-setup-tg-token", timeout=15000)
        assert not await page.locator("#fp-setup-tg-targets").is_enabled()

        await page.fill("#fp-setup-tg-token", "123:abc")
        await page.click("#fp-setup-tg-connect")
        await page.wait_for_function(
            "document.getElementById('fp-setup-tg-connect')"
            ".nextElementSibling.textContent.includes('Family')",
            timeout=15000,
        )
        assert await page.locator("#fp-setup-tg-targets").is_enabled()
        assert await page.locator("#fp-setup-tg-save-targets").is_enabled()
        assert await page.locator("#fp-setup-tg-find-chats").is_enabled()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_wizard_enter_targets_error_is_styled_as_an_error(page, base_url):
    """UAT6-N15: "Enter at least one target first." used to read as plain grey
    `.modal-note` text, indistinguishable from an ordinary status line."""
    try:
        await _open_notifications_step(page, base_url)
        await page.click("#fp-setup-tg-save-targets")
        status = page.locator("#fp-setup-tg-targets-status")
        await status.wait_for(state="visible")
        assert await status.get_attribute("role") == "alert"
        assert await status.get_attribute("class") == "fp-dialog-error"
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_targets_placeholder_is_not_clipped_at_375(page, base_url):
    """UAT6-N34: no width rule at all on this input meant the browser's
    intrinsic ~20-character box clipped "Chat ID, @username, or several
    separated by commas" down to "...or sever" on a phone-width wizard."""
    await page.set_viewport_size({"width": 375, "height": 800})
    try:
        await _open_notifications_step(page, base_url)
        box = await page.locator("#fp-setup-tg-targets").bounding_box()
        card_box = await page.locator("#setup-view").bounding_box()
        assert box["width"] >= card_box["width"] - 80, (box, card_box)
    finally:
        await page.set_viewport_size({"width": 1280, "height": 900})
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)

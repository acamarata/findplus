"""Browser tests for the setup wizard's Notifications step: the Telegram
Targets field and "Find chat IDs" helper (multi-target Telegram support).
Split from test_setup_wizard_notifications.py so this ticket's tests have
their own file rather than growing a file shared with the wizard-visuals
work happening in the same repo.
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


async def _open_notifications_step(page, base_url):
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

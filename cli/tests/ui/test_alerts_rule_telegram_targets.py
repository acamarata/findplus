"""Browser tests for the add/edit-rule dialog's per-rule Telegram target
picker (WP10, gap-audit P13).

Telegram "configured" state is seeded by writing alerts.json directly at
FINDPLUS_STATE_DIR (same pattern test_alerts_telegram_targets.py uses) --
never through PUT /api/alerts/channels/telegram, which would call the real
Telegram getMe API and trip the non-loopback network guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")

FAKE_TOKEN = "fake-token-123456:ABCDEFGHIJabcdefghij"


@pytest.fixture
def configured_telegram(ui_env: dict):
    """Two saved targets with labels, so the picker has something to show."""
    path = Path(ui_env["FINDPLUS_STATE_DIR"]) / "alerts.json"
    path.write_text(
        json.dumps(
            {
                "channels": {
                    "telegram": {
                        "bot_token": FAKE_TOKEN,
                        "chat_ids": ["111", "-100222"],
                        "chat_labels": ["@alice", "Family"],
                        "chat_title": "Test Chat",
                        "bot_username": "test_bot",
                        "captured_at": "2026-01-01T00:00:00+00:00",
                    }
                }
            }
        )
    )
    yield
    path.write_text(json.dumps({"channels": {}}))


async def _open_fresh_add_rule_dialog(page):
    await page.click("#fp-add-rule-btn")
    await page.wait_for_selector("#fp-add-rule-dialog[open]")
    await page.wait_for_function(
        "document.querySelector('#fp-rule-channels input[data-channel=telegram]')?.checked === true"
    )


async def test_field_is_hidden_until_telegram_is_ticked(
    page, base_url, configured_telegram
) -> None:
    await open_alerts_tab(page, base_url)
    await page.click("#fp-add-rule-btn")
    await page.wait_for_selector("#fp-add-rule-dialog[open]")
    await page.wait_for_function(
        "document.getElementById('fp-rule-telegram-targets-field') !== null"
    )
    # telegram defaults ticked (it is the only connected channel here), so the
    # field is visible as soon as the dialog's real render lands.
    await page.wait_for_function(
        "!document.getElementById('fp-rule-telegram-targets-field').hidden"
    )
    await page.uncheck("#fp-rule-channels input[data-channel=telegram]")
    assert await page.locator("#fp-rule-telegram-targets-field").is_hidden()


async def test_all_chats_is_the_default_and_hides_the_per_chat_list(
    page, base_url, configured_telegram
) -> None:
    await open_alerts_tab(page, base_url)
    await _open_fresh_add_rule_dialog(page)
    assert await page.locator("#fp-rule-telegram-all-chats").is_checked()
    assert await page.locator("#fp-rule-telegram-targets-list").is_hidden()


async def test_unticking_all_chats_reveals_a_checkbox_per_saved_target(
    page, base_url, configured_telegram
) -> None:
    await open_alerts_tab(page, base_url)
    await _open_fresh_add_rule_dialog(page)
    await page.uncheck("#fp-rule-telegram-all-chats")
    assert await page.locator("#fp-rule-telegram-targets-list").is_visible()
    labels = await page.locator("#fp-rule-telegram-targets-list").inner_text()
    assert "@alice" in labels
    assert "Family" in labels


async def test_save_with_all_chats_sends_null_telegram_targets(
    page, base_url, configured_telegram
) -> None:
    captured = {}

    async def rules_route(route):
        # loadRules() also GETs this same path (tab load, and again after a
        # successful save) -- only the POST this test cares about is faked.
        if route.request.method != "POST":
            await route.continue_()
            return
        captured["body"] = json.loads(route.request.post_data)
        await route.fulfill(status=201, content_type="application/json", body=json.dumps({"id": 1}))

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/rules", rules_route)
    await _open_fresh_add_rule_dialog(page)
    await page.fill("#fp-rule-name", "all chats rule")
    await page.select_option("#fp-rule-device", label="Ali's Keys")
    await page.click("#fp-rule-save")
    await page.wait_for_function("() => !document.getElementById('fp-add-rule-dialog').open")
    assert captured["body"]["telegram_targets"] is None


async def test_save_with_a_picked_subset_sends_exactly_that_subset(
    page, base_url, configured_telegram
) -> None:
    captured = {}

    async def rules_route(route):
        # loadRules() also GETs this same path (tab load, and again after a
        # successful save) -- only the POST this test cares about is faked.
        if route.request.method != "POST":
            await route.continue_()
            return
        captured["body"] = json.loads(route.request.post_data)
        await route.fulfill(status=201, content_type="application/json", body=json.dumps({"id": 1}))

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/rules", rules_route)
    await _open_fresh_add_rule_dialog(page)
    await page.fill("#fp-rule-name", "one chat rule")
    await page.select_option("#fp-rule-device", label="Ali's Keys")
    await page.uncheck("#fp-rule-telegram-all-chats")
    await page.check("#fp-rule-telegram-targets-list input[data-channel='-100222']")
    await page.click("#fp-rule-save")
    await page.wait_for_function("() => !document.getElementById('fp-add-rule-dialog').open")
    assert captured["body"]["telegram_targets"] == ["-100222"]


async def test_editing_a_narrowed_rule_reopens_with_its_subset_ticked(
    page, base_url, configured_telegram
) -> None:
    create_resp = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            {
                "name": "narrowed",
                "device_id": "TAG-HOME",
                "channels": ["telegram"],
                "telegram_targets": ["111"],
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert create_resp.ok, await create_resp.text()
    rule_id = (await create_resp.json())["id"]
    try:
        await open_alerts_tab(page, base_url)
        row = page.locator("#fp-rules-tbody tr", has_text="narrowed")
        await row.wait_for(state="visible")
        await row.get_by_text("Edit", exact=True).click()
        await page.wait_for_selector("#fp-add-rule-dialog[open]")
        await page.wait_for_function(
            "document.getElementById('fp-rule-telegram-all-chats').checked === false"
        )
        checked = await page.locator(
            "#fp-rule-telegram-targets-list input[data-channel='111']"
        ).is_checked()
        assert checked
    finally:
        await page.request.delete(f"{base_url}/api/alerts/rules/{rule_id}")

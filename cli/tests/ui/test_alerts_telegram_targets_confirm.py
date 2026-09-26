"""Playwright browser tests for the Telegram target chip's confirm-before-
remove flow (UAT7 N04: a target still used by an alert rule). Split out of
test_alerts_telegram_targets.py at the PRI rule-7 300-line file cap.

Seed data (cli/tests/ui/conftest.py): device "TAG-HOME". Telegram is seeded
by writing alerts.json directly (shaped bot token, never a real getMe call)
-- the same pattern test_alerts_telegram_targets.py uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")

_SHAPED_TOKEN = "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678"


@pytest.fixture
def two_saved_targets(ui_env: dict):
    path = Path(ui_env["FINDPLUS_STATE_DIR"]) / "alerts.json"
    path.write_text(
        json.dumps(
            {
                "channels": {
                    "telegram": {
                        "bot_token": _SHAPED_TOKEN,
                        "chat_ids": ["11111", "22222"],
                        "chat_labels": ["Family chat", "22222"],
                        "chat_title": "Test Chat",
                        "bot_username": "test_bot",
                        "captured_at": "2026-01-01T00:00:00+00:00",
                    }
                }
            }
        )
    )
    yield path
    path.write_text(json.dumps({"channels": {}}))


async def _create_telegram_rule(page, base_url: str, name: str) -> int:
    """A rule with `telegram_targets: null` ("All chats") -- it uses every
    saved target, so removing either one should warn."""
    rule = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps({"name": name, "device_id": "TAG-HOME", "channels": ["telegram"]}),
        headers={"Content-Type": "application/json"},
    )
    assert rule.ok, await rule.text()
    return (await rule.json())["id"]


async def _rules_using_telegram_target(page, base_url: str, chat_id: str) -> int:
    """Mirrors alerts_telegram_targets.js's own countRulesUsing() -- the
    rules table is shared for the whole session, so this test computes its
    expected count from the server's own current state instead of assuming
    a clean baseline (UAT7 N04's own client code makes exactly this same
    GET /api/alerts/rules call before it ever shows the confirm dialog)."""
    rules = await (await page.request.get(f"{base_url}/api/alerts/rules")).json()
    return sum(
        1
        for r in rules
        if "telegram" in r["channels"]
        and (r["telegram_targets"] is None or chat_id in r["telegram_targets"])
    )


async def test_removing_a_chip_used_by_a_rule_confirms_first(page, base_url, two_saved_targets):
    rule_id = await _create_telegram_rule(page, base_url, "N04 confirm rule")
    try:
        expected_count = await _rules_using_telegram_target(page, base_url, "11111")
        assert expected_count >= 1, "the rule just created must count itself"
        await open_alerts_tab(page, base_url)
        chips = page.locator("#fp-tg-current-targets li")
        await chips.first.wait_for(state="visible")
        await (
            page.locator("#fp-tg-current-targets li", has_text="Family chat")
            .locator("button.fp-chip-remove")
            .click()
        )
        await page.wait_for_selector("#fp-confirm-dialog[open]")
        dialog_text = await page.locator("#fp-confirm-dialog").inner_text()
        assert "Family chat" in dialog_text
        assert str(expected_count) in dialog_text
        await page.locator("#fp-confirm-dialog").get_by_role("button", name="Remove").click()
        await page.wait_for_function(
            "document.querySelectorAll('#fp-tg-current-targets li').length === 1"
        )
        saved = json.loads(two_saved_targets.read_text())["channels"]["telegram"]["chat_ids"]
        assert saved == ["22222"]
    finally:
        await page.request.delete(f"{base_url}/api/alerts/rules/{rule_id}")


async def test_declining_the_confirm_leaves_the_target_in_place(page, base_url, two_saved_targets):
    rule_id = await _create_telegram_rule(page, base_url, "N04 cancel rule")
    try:
        await open_alerts_tab(page, base_url)
        chips = page.locator("#fp-tg-current-targets li")
        await chips.first.wait_for(state="visible")
        await (
            page.locator("#fp-tg-current-targets li", has_text="Family chat")
            .locator("button.fp-chip-remove")
            .click()
        )
        await page.wait_for_selector("#fp-confirm-dialog[open]")
        await page.locator("#fp-confirm-dialog").get_by_role("button", name="Cancel").click()
        await page.wait_for_function("() => !document.getElementById('fp-confirm-dialog').open")
        assert await chips.count() == 2
        saved = json.loads(two_saved_targets.read_text())["channels"]["telegram"]["chat_ids"]
        assert saved == ["11111", "22222"]
    finally:
        await page.request.delete(f"{base_url}/api/alerts/rules/{rule_id}")

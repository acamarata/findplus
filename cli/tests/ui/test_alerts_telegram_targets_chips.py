"""Playwright browser tests for the Telegram target chip row's own rendering
and its no-confirmation-needed remove path (UAT7 N04). Split out of
test_alerts_telegram_targets.py at the PRI rule-7 300-line file cap; the
confirm-first path (a target a rule actually uses) lives in
test_alerts_telegram_targets_confirm.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import open_alerts_tab
from .test_alerts_telegram_targets import configured_telegram

pytestmark = pytest.mark.asyncio(loop_scope="session")

__all__ = ["configured_telegram"]  # re-exported fixture, not unused


async def test_current_targets_render_as_chips(page, base_url, configured_telegram):
    """UAT7 N04: a real chip (span + small "x" remove button), not a bulleted
    <li> with a separate full "Remove" button -- channels_response()'s
    target_labels (falling back to the raw id, this fixture's target has no
    chat_labels)."""
    await open_alerts_tab(page, base_url)
    chips = page.locator("#fp-tg-current-targets li.fp-chip")
    await chips.first.wait_for(state="visible")
    assert await chips.count() == 1
    text = await chips.first.inner_text()
    assert "11111" in text
    remove_btn = chips.first.locator("button.fp-chip-remove")
    assert await remove_btn.get_attribute("aria-label") == "Remove 11111"
    for control_id in ("fp-tg-targets", "fp-tg-save-targets", "fp-tg-find-chats"):
        assert not await page.is_disabled(f"#{control_id}"), control_id


async def _clear_leftover_all_chats_telegram_rules(page, base_url: str) -> None:
    """The rules table is shared for the whole session: a `telegram_targets:
    null` rule left over from an earlier test counts as using every chat id
    -- cleared first so this file's own "unused" test stays about its own
    two fresh ids, not whatever another test forgot to clean up."""
    for rule in await (await page.request.get(f"{base_url}/api/alerts/rules")).json():
        if "telegram" in rule["channels"] and rule["telegram_targets"] is None:
            await page.request.delete(f"{base_url}/api/alerts/rules/{rule['id']}")


def _seed_two_targets(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "channels": {
                    "telegram": {
                        "bot_token": "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678",
                        "chat_ids": ["11111", "22222"],
                        "chat_title": "Test Chat",
                        "bot_username": "test_bot",
                        "captured_at": "2026-01-01T00:00:00+00:00",
                    }
                }
            }
        )
    )


async def test_removing_an_unused_chip_needs_no_confirmation(page, base_url, ui_env):
    """A target no rule uses is removed straight away -- nothing else
    changes, so nothing to warn about (UAT7 N04)."""
    await _clear_leftover_all_chats_telegram_rules(page, base_url)
    path = Path(ui_env["FINDPLUS_STATE_DIR"]) / "alerts.json"
    _seed_two_targets(path)
    try:
        await open_alerts_tab(page, base_url)
        chips = page.locator("#fp-tg-current-targets li")
        await chips.first.wait_for(state="visible")
        assert await chips.count() == 2
        await (
            page.locator("#fp-tg-current-targets li", has_text="11111")
            .locator("button.fp-chip-remove")
            .click()
        )
        await page.wait_for_function(
            "document.querySelectorAll('#fp-tg-current-targets li').length === 1"
        )
        assert await page.locator("#fp-confirm-dialog[open]").count() == 0
        remaining = await chips.first.inner_text()
        assert "22222" in remaining
        saved = json.loads(path.read_text())["channels"]["telegram"]["chat_ids"]
        assert saved == ["22222"]
    finally:
        path.write_text(json.dumps({"channels": {}}))

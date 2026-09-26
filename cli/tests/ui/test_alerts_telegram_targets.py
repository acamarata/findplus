"""Playwright browser tests for the Alerts tab's Telegram target chips and
the "Find chat IDs" helper (multi-target Telegram support, chips UAT7 N04).

Telegram "configured" state is seeded by writing alerts.json directly at
FINDPLUS_STATE_DIR (same pattern test_alerts_telegram.py uses) -- never
through PUT /api/alerts/channels/telegram, which would call the real
Telegram getMe API and trip the non-loopback network guard from
cli/tests/conftest.py. `GET .../updates` and `POST /api/alerts/test` are
stubbed with page.route so no test here touches the network either.

The confirm-before-remove flow (UAT7 N04: a target still used by a rule)
moved to test_alerts_telegram_targets_confirm.py at the PRI rule-7 300-line
file cap.
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
    """Seed a configured Telegram channel (one existing target) by writing
    alerts.json directly."""
    path = Path(ui_env["FINDPLUS_STATE_DIR"]) / "alerts.json"
    path.write_text(
        json.dumps(
            {
                "channels": {
                    "telegram": {
                        "bot_token": FAKE_TOKEN,
                        "chat_ids": ["11111"],
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


async def test_add_chats_field_always_renders_empty(page, base_url, configured_telegram):
    """UAT7 N04: add-only now -- the field never shows the stored id list,
    even though one chip is already saved."""
    await open_alerts_tab(page, base_url)
    chip = page.locator("#fp-tg-current-targets li")
    await chip.first.wait_for(state="visible")
    assert await page.locator("#fp-tg-targets").input_value() == ""


async def test_add_chats_merges_new_targets_onto_the_existing_ones(
    page, base_url, configured_telegram
):
    """UAT7 N04: Add chats PUTs the already-saved id plus the newly typed
    ones, never just what is in the field -- the field holds only the new
    entries, so this proves the merge, not a re-typed full list."""
    saved = {}

    async def targets_route(route):
        saved["body"] = json.loads(route.request.post_data)
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"telegram": {"configured": True, "targets": "11111,222,@person"}}),
        )

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/channels/telegram/targets", targets_route)
    await page.fill("#fp-tg-targets", " 222, @person ")
    await page.click("#fp-tg-save-targets")
    await page.wait_for_function(
        "document.getElementById('fp-tg-targets-status').textContent.length > 0"
    )
    assert saved["body"] == {"targets": "11111,222,@person"}
    status = await page.locator("#fp-tg-targets-status").inner_text()
    assert "saved" in status.lower()
    # The field clears once the add succeeds -- nothing left over to re-add.
    assert await page.locator("#fp-tg-targets").input_value() == ""


async def test_add_chats_with_empty_field_shows_a_hint_and_makes_no_request(
    page, base_url, configured_telegram
):
    called = {"count": 0}

    async def targets_route(route):
        called["count"] += 1
        await route.fulfill(status=200, content_type="application/json", body="{}")

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/channels/telegram/targets", targets_route)
    await page.fill("#fp-tg-targets", "")
    await page.click("#fp-tg-save-targets")
    await page.wait_for_function(
        "document.getElementById('fp-tg-targets-status').textContent.length > 0"
    )
    assert called["count"] == 0


async def test_add_chats_bad_entry_shows_the_server_detail(page, base_url, configured_telegram):
    async def targets_route(route):
        await route.fulfill(
            status=422,
            content_type="application/json",
            body=json.dumps({"detail": "invalid Telegram target 'not-a-target': ..."}),
        )

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/channels/telegram/targets", targets_route)
    await page.fill("#fp-tg-targets", "not-a-target")
    await page.click("#fp-tg-save-targets")
    await page.wait_for_function(
        "document.getElementById('fp-tg-targets-status').textContent.includes('not-a-target')"
    )


async def test_find_chat_ids_lists_chats_and_marks_an_already_saved_one(
    page, base_url, configured_telegram
):
    """UAT7 N04: a chat already saved (its id is "11111", this fixture's own
    target) shows "Added" instead of an actionable "Add" -- clicking it again
    used to offer no new target."""

    async def updates_route(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "chats": [
                        {"id": "222", "type": "private", "title": "Alice", "username": "alice"},
                        {"id": "11111", "type": "private", "title": "Me", "username": None},
                    ]
                }
            ),
        )

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/channels/telegram/updates", updates_route)
    await page.click("#fp-tg-find-chats")
    await page.wait_for_selector("#fp-tg-chats-list li")
    items = page.locator("#fp-tg-chats-list li")
    assert await items.count() == 2

    alice_row = page.locator("#fp-tg-chats-list li", has_text="Alice")
    added_row = page.locator("#fp-tg-chats-list li", has_text="11111")
    assert not await alice_row.locator("button").is_disabled()
    assert await added_row.locator("button").is_disabled()
    assert "added" in (await added_row.locator("button").inner_text()).lower()

    # Clicking "Add" on the not-yet-saved chat appends its id to the field.
    await alice_row.locator("button").click()
    value = await page.locator("#fp-tg-targets").input_value()
    assert "222" in value


async def test_find_chat_ids_no_updates_yet_shows_the_instruction(
    page, base_url, configured_telegram
):
    async def updates_route(route):
        await route.fulfill(status=200, content_type="application/json", body='{"chats": []}')

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/channels/telegram/updates", updates_route)
    await page.click("#fp-tg-find-chats")
    await page.wait_for_function(
        "document.getElementById('fp-tg-targets-status').textContent.toLowerCase().includes('message')"
    )
    status = await page.locator("#fp-tg-targets-status").inner_text()
    assert "message" in status.lower()
    assert await page.locator("#fp-tg-chats-list").is_hidden()


async def test_find_chat_ids_never_shows_the_bot_token(page, base_url, configured_telegram):
    async def updates_route(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"chats": [{"id": "1", "type": "private", "title": "A", "username": None}]}
            ),
        )

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/channels/telegram/updates", updates_route)
    await page.click("#fp-tg-find-chats")
    await page.wait_for_selector("#fp-tg-chats-list li")
    body_text = await page.locator("#fp-tg-chats-list").inner_text()
    assert FAKE_TOKEN not in body_text


async def test_send_test_reports_per_target_results(page, base_url, configured_telegram):
    async def test_route(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "status": "partial",
                    "error": "blocked",
                    "results": [
                        {"target": "11111", "status": "sent", "error": None},
                        {"target": "22222", "status": "failed", "error": "blocked"},
                    ],
                }
            ),
        )

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/test", test_route)
    await page.click("#fp-tg-test")
    await page.wait_for_function(
        "document.getElementById('fp-tg-status').textContent.includes('11111')"
    )
    status = await page.locator("#fp-tg-status").inner_text()
    assert "11111" in status and "sent" in status
    assert "22222" in status and "blocked" in status


async def test_targets_disabled_until_a_bot_is_connected(page, base_url, ui_env):
    """UAT6 N15: Add chats/Find chat IDs used to be live before a bot was
    ever connected, only answering "Telegram not configured" once clicked --
    disabled here instead, with a one-line reason in their place."""
    Path(ui_env["FINDPLUS_STATE_DIR"], "alerts.json").write_text(json.dumps({"channels": {}}))
    await open_alerts_tab(page, base_url)
    for control_id in ("fp-tg-targets", "fp-tg-save-targets", "fp-tg-find-chats"):
        assert await page.is_disabled(f"#{control_id}"), control_id
    reason = page.locator("#fp-tg-targets-disabled-reason")
    assert await reason.is_visible()
    assert (await reason.inner_text()).strip() != ""


# test_current_targets_render_as_chips and
# test_removing_an_unused_chip_needs_no_confirmation moved to
# test_alerts_telegram_targets_chips.py at the PRI rule-7 300-line file cap
# (this file's own `configured_telegram` fixture is re-exported there).

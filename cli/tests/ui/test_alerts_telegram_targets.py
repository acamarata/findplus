"""Playwright browser tests for the Alerts tab's Telegram Targets field and
the "Find chat IDs" helper (multi-target Telegram support).

Telegram "configured" state is seeded by writing alerts.json directly at
FINDPLUS_STATE_DIR (same pattern test_alerts_telegram.py uses) -- never
through PUT /api/alerts/channels/telegram, which would call the real
Telegram getMe API and trip the non-loopback network guard from
cli/tests/conftest.py. `GET .../updates` and `POST /api/alerts/test` are
stubbed with page.route so no test here touches the network either.
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


async def test_targets_field_shows_the_stored_targets(page, base_url, configured_telegram):
    await open_alerts_tab(page, base_url)
    await page.wait_for_function("document.getElementById('fp-tg-targets').value.length > 0")
    assert await page.locator("#fp-tg-targets").input_value() == "11111"


async def test_save_targets_puts_the_parsed_comma_list(page, base_url, configured_telegram):
    saved = {}

    async def targets_route(route):
        saved["body"] = json.loads(route.request.post_data)
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"telegram": {"configured": True, "targets": "111,-100222,@person"}}),
        )

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/channels/telegram/targets", targets_route)
    await page.fill("#fp-tg-targets", " 111, -100222, @person ")
    await page.click("#fp-tg-save-targets")
    await page.wait_for_function(
        "document.getElementById('fp-tg-targets-status').textContent.length > 0"
    )
    # saveTelegramTargets() trims the field's raw value before PUTting it
    # (alerts_telegram_targets.js) -- the server does its own comma-level
    # trim/validate via alerts/targets.py, this is just "don't send a
    # leading/trailing space around the whole string".
    assert saved["body"] == {"targets": "111, -100222, @person"}
    status = await page.locator("#fp-tg-targets-status").inner_text()
    assert "saved" in status.lower()


async def test_save_targets_with_empty_field_shows_a_hint_and_makes_no_request(
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


async def test_save_targets_bad_entry_shows_the_server_detail(page, base_url, configured_telegram):
    async def targets_route(route):
        await route.fulfill(
            status=422,
            content_type="application/json",
            body=json.dumps({"detail": "invalid Telegram target 'not-a-target': ..."}),
        )

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/channels/telegram/targets", targets_route)
    await page.fill("#fp-tg-targets", "111,not-a-target")
    await page.click("#fp-tg-save-targets")
    await page.wait_for_function(
        "document.getElementById('fp-tg-targets-status').textContent.includes('not-a-target')"
    )


async def test_find_chat_ids_lists_chats_with_an_add_action(page, base_url, configured_telegram):
    async def updates_route(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "chats": [
                        {"id": "222", "type": "private", "title": "Alice", "username": "alice"},
                        {
                            "id": "-100333",
                            "type": "supergroup",
                            "title": "Family",
                            "username": None,
                        },
                    ]
                }
            ),
        )

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/channels/telegram/updates", updates_route)
    await page.click("#fp-tg-find-chats")
    await page.wait_for_selector("#fp-tg-chats-list li")
    items = await page.locator("#fp-tg-chats-list li").all_text_contents()
    assert any("Alice" in i and "222" in i for i in items)
    assert any("Family" in i and "-100333" in i for i in items)

    # Clicking "Add" on the first chat appends its id to the targets field
    # without clobbering the target already there (E13-style focus-safety:
    # this is a plain value append, not a re-render).
    await page.fill("#fp-tg-targets", "11111")
    await page.locator("#fp-tg-chats-list li", has_text="Alice").locator("button").click()
    value = await page.locator("#fp-tg-targets").input_value()
    assert "11111" in value
    assert "222" in value


async def test_find_chat_ids_no_updates_yet_shows_the_instruction(
    page, base_url, configured_telegram
):
    async def updates_route(route):
        await route.fulfill(status=200, content_type="application/json", body='{"chats": []}')

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/channels/telegram/updates", updates_route)
    await page.click("#fp-tg-find-chats")
    # The interim "Looking for chats..." status also has non-zero length,
    # so this waits for the FINAL text specifically, not just any text.
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

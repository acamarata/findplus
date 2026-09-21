"""Playwright browser tests for the Alerts tab's Telegram channel section
(P1-E10-W7-S2-T1/T2; split from test_alerts.py, E13 loop3 L3-4).

Telegram "configured" state is seeded by writing alerts.json directly at
FINDPLUS_STATE_DIR (never through PUT /api/alerts/channels/telegram, which
calls the real Telegram getMe API and would trip the non-loopback network
guard from cli/tests/conftest.py). `open_alerts_tab()` is shared across every
test_alerts_* file via conftest.py.
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
    """Seed a configured Telegram channel by writing alerts.json directly."""
    path = Path(ui_env["FINDPLUS_STATE_DIR"]) / "alerts.json"
    path.write_text(
        json.dumps(
            {
                "channels": {
                    "telegram": {
                        "bot_token": FAKE_TOKEN,
                        "chat_id": "99999",
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


async def test_telegram_token_field_masked(page, base_url, configured_telegram):
    await open_alerts_tab(page, base_url)
    token_input = page.locator("#fp-tg-token")
    # #fp-telegram-section is static markup, present before loadChannels()'s
    # GET /api/alerts/channels resolves -- renderTelegramSection() only
    # applies the mask once that fetch lands, so reading input_value() right
    # after the selector wait races an unawaited fetch (alerts.js's init()
    # fires refreshAll() without awaiting it) and can read the pre-load
    # empty value on a slower CI runner. Wait on the mask class itself,
    # matching test_widget_map_toggle_persists's pattern (test_alerts_rules.py).
    await page.wait_for_function(
        "document.getElementById('fp-tg-token').classList.contains('fp-token-masked')"
    )
    value = await token_input.input_value()
    assert "••" in value
    assert "fake-token-1234" not in value


async def test_telegram_token_cleared_on_focus(page, base_url, configured_telegram):
    await open_alerts_tab(page, base_url)
    token_input = page.locator("#fp-tg-token")
    await token_input.focus()
    assert await token_input.input_value() == ""


async def test_clear_telegram_channel_round_trips(page, base_url, configured_telegram):
    """loop2 B3: clearTelegramChannel() used to bypass api() with a raw
    fetch(), so a successful clear was never actually verified end to end."""
    await open_alerts_tab(page, base_url)
    await page.click("#fp-tg-clear")
    await page.wait_for_function(
        """async () => {
            const r = await fetch('/api/alerts/channels');
            const body = await r.json();
            return body.telegram.configured === false;
        }"""
    )


async def test_clear_telegram_channel_surfaces_a_failed_delete(page, base_url, configured_telegram):
    """loop2 B3: a non-401 DELETE failure used to be silently swallowed (no
    res.ok check, no try/catch) while loadChannels() still ran unconditionally
    afterward, and the promise rejection escaped the click handler unhandled."""

    async def fail_delete(route):
        await route.fulfill(status=500, content_type="application/json", body='{"detail":"boom"}')

    await open_alerts_tab(page, base_url)
    await page.route("**/api/alerts/channels/telegram", fail_delete)
    await page.click("#fp-tg-clear")
    await page.wait_for_function("document.getElementById('fp-tg-status').textContent.length > 0")
    assert "boom" in await page.locator("#fp-tg-status").inner_text()

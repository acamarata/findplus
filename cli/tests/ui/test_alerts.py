"""Playwright browser tests for the Alerts tab (P1-E10-W7-S2-T1/T2).

Seed data (cli/tests/ui/conftest.py): device "TAG-HOME" ("Home Tag"), place
"Home", group "Family" — reused here for the add-rule dialog instead of
inserting new rows. Telegram "configured" state is seeded by writing
alerts.json directly at FINDPLUS_STATE_DIR (never through PUT
/api/alerts/channels/telegram, which calls the real Telegram getMe API and
would trip the non-loopback network guard from cli/tests/conftest.py).

Prerequisite check (ai_instructions step 2): button[data-tab="alerts"] and
#tab-alerts exist in web/index.html as of P1-E10-W7-S2-T1's corrected
output, applied in the same dispatch as this file — every test below runs
against real selectors, none are BLOCKED. The one exception is
test_widget_map_toggle_persists: /api/settings/widget.show_map is not
registered server-side (build-notes.md defect #36, § E10-S2), so it is
skipped with that reason rather than asserted against selectors that do
not yet round-trip any state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


async def _open_alerts_tab(page, base_url):
    await page.goto(base_url + "/")
    await page.click('button[data-tab="alerts"]')
    await page.wait_for_selector("#fp-telegram-section")


async def test_alerts_tab_visible(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector('button[data-tab="alerts"]')
    await page.click('button[data-tab="alerts"]')
    await page.wait_for_selector("#tab-alerts:not([hidden])")


async def test_telegram_token_field_masked(page, base_url, configured_telegram):
    await _open_alerts_tab(page, base_url)
    token_input = page.locator("#fp-tg-token")
    value = await token_input.input_value()
    assert "••" in value
    assert "fake-token-1234" not in value


async def test_telegram_token_cleared_on_focus(page, base_url, configured_telegram):
    await _open_alerts_tab(page, base_url)
    token_input = page.locator("#fp-tg-token")
    await token_input.focus()
    assert await token_input.input_value() == ""


async def test_alerts_latency_disclaimer_present(page, base_url):
    await _open_alerts_tab(page, base_url)
    notice = page.locator("#fp-alerts-latency-notice")
    await notice.wait_for(state="visible")
    assert (
        "Alerts inherit the network's delay. An arrival or departure may be "
        "reported minutes to hours late." in await notice.inner_text()
    )


async def test_webhook_save(page, base_url):
    await _open_alerts_tab(page, base_url)
    await page.fill("#fp-webhook-url", "http://localhost:9999/hook")
    await page.click("#fp-webhook-save")
    await page.wait_for_function(
        """async () => {
            const r = await fetch('/api/alerts/channels');
            const body = await r.json();
            return body.webhook.configured && body.webhook.url === 'http://localhost:9999/hook';
        }"""
    )
    resp = await page.request.get(base_url + "/api/alerts/channels")
    channels = await resp.json()
    assert channels["webhook"]["configured"] is True
    assert channels["webhook"]["url"] == "http://localhost:9999/hook"


async def test_add_rule_creates_row(page, base_url):
    await _open_alerts_tab(page, base_url)
    await page.click("#fp-add-rule-btn")
    await page.wait_for_selector("#fp-add-rule-dialog[open]")
    await page.fill("#fp-rule-name", "Home arrival test")
    await page.select_option("#fp-rule-place", label="Home")
    await page.select_option("#fp-rule-device", label="Home Tag")
    await page.check("#fp-rule-on-enter")
    await page.click("#fp-rule-save")
    await page.wait_for_function("() => !document.getElementById('fp-add-rule-dialog').open")
    row = page.locator("#fp-rules-tbody tr", has_text="Home arrival test")
    await row.wait_for(state="visible")


async def test_delete_rule_removes_row(page, base_url):
    create_resp = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            {
                "name": "Delete me rule",
                "device_id": "TAG-HOME",
                "channel": "webhook",
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert create_resp.ok, await create_resp.text()

    await _open_alerts_tab(page, base_url)
    row = page.locator("#fp-rules-tbody tr", has_text="Delete me rule")
    await row.wait_for(state="visible")
    page.once("dialog", lambda d: d.accept())  # window.confirm() -> true
    await row.get_by_text("Delete", exact=True).click()
    await page.wait_for_function(
        """async () => {
            const r = await fetch('/api/alerts/rules');
            const rules = await r.json();
            return !rules.some((r) => r.name === 'Delete me rule');
        }"""
    )


async def test_widget_map_toggle_persists(page, base_url):
    pytest.skip(
        "BLOCKED: /api/settings/widget.show_map is not registered server-side "
        "(build-notes.md defect #36; alerts.js's per-key GET/POST calls 404 and "
        "are swallowed, see P1-E10-W7-S2-T1's recorded deviation). The checkbox "
        "cannot round-trip any state until that route lands."
    )

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
against real selectors. test_widget_map_toggle_persists was skipped until
P1-E10-S2's fix landed GET/PUT/POST /api/settings/widget.show_map
server-side (build-notes.md defect #36); it now round-trips for real.
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
    """The saved URL comes back MASKED: a webhook path is a bearer credential,
    so the browser gets scheme://host plus the last few characters and never
    the routable path (security review finding 5)."""
    await _open_alerts_tab(page, base_url)
    await page.fill("#fp-webhook-url", "http://localhost:9999/hook-abcd1234")
    await page.click("#fp-webhook-save")
    await page.wait_for_function(
        """async () => {
            const r = await fetch('/api/alerts/channels');
            const body = await r.json();
            return body.webhook.configured && body.webhook.url.startsWith('http://localhost:9999/');
        }"""
    )
    resp = await page.request.get(base_url + "/api/alerts/channels")
    channels = await resp.json()
    assert channels["webhook"]["configured"] is True
    assert channels["webhook"]["url"] == "http://localhost:9999/…1234"
    assert "hook-abcd" not in channels["webhook"]["url"]


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
    await _open_alerts_tab(page, base_url)
    toggle = page.locator("#fp-widget-map-toggle")
    await toggle.wait_for(state="visible")
    assert await toggle.is_checked() is False

    await toggle.check()
    await page.wait_for_function(
        """async () => {
            const r = await fetch('/api/settings/widget.show_map');
            const body = await r.json();
            return body['widget.show_map'] === true;
        }"""
    )

    # A fresh load (not a page.reload() + a second goto — that raced the
    # checkbox's static markup, which is visible before loadWidgetToggle()'s
    # async GET sets .checked, against is_checked() below).
    await _open_alerts_tab(page, base_url)
    await page.wait_for_function("document.getElementById('fp-widget-map-toggle').checked === true")


async def test_delivery_log_shows_channel_and_status(page, base_url, ui_db):
    """CF-14: alert_deliveries rows existed since 1.0 but no UI ever read them.

    The rule is created through the API so the server owns it; the delivery row is
    written straight into the live SQLite file, because the only code that writes
    one is the poller's dispatch pass and this test is about the view, not the
    dispatcher. The assertion is on the rendered row, not the endpoint — the
    endpoint already worked and the gap was that nothing displayed it.
    """
    import sqlite3

    rule = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            {"name": "Delivery log rule", "device_id": "TAG-HOME", "channel": "webhook"}
        ),
        headers={"Content-Type": "application/json"},
    )
    assert rule.ok, await rule.text()
    rule_id = (await rule.json())["id"]

    conn = sqlite3.connect(ui_db)
    try:
        conn.execute(
            "INSERT INTO alert_deliveries"
            " (rule_id, event_kind, event_id, channel, sent_at, status, error)"
            " VALUES (?, 'device', 4242, 'webhook', '2026-09-20 12:00:00', 'failed',"
            " 'connection refused')",
            (rule_id,),
        )
        conn.commit()
    finally:
        conn.close()

    await _open_alerts_tab(page, base_url)
    await page.wait_for_selector("#fp-deliveries-table")
    headers = await page.locator("#fp-deliveries-table thead th").all_text_contents()
    assert headers == ["Rule", "Channel", "Kind", "Sent", "Status", "Error"]

    row = page.locator("#fp-deliveries-tbody tr", has_text="Delivery log rule")
    await row.wait_for(state="visible")
    cells = await row.locator("td").all_text_contents()

    assert cells[1] == "webhook"
    assert cells[4] == "failed"
    assert cells[5] == "connection refused"


async def test_the_rule_dialog_sends_null_for_an_unchosen_select(page, base_url):
    """honesty round 3 F8: Number("") is 0, and no place has id 0.

    With no places saved the select was empty, so the save posted place_id 0;
    PRAGMA foreign_keys=ON turned that into an IntegrityError and the dialog
    showed a raw 500. null is what "nothing chosen" means.
    """
    await _open_alerts_tab(page, base_url)

    body = await page.evaluate(
        """async () => {
            const rules = await import('/static/app/alerts_rules.js');
            const sent = [];
            const realFetch = window.fetch;
            window.fetch = async (url, opts) => {
                if (String(url).includes('/api/alerts/rules') && opts && opts.method === 'POST') {
                    sent.push(JSON.parse(opts.body));
                    return new Response('{}', { status: 200 });
                }
                return realFetch(url, opts);
            };
            try {
                rules.openAddRuleDialog();
                document.getElementById('fp-rule-name').value = 'r1';
                document.getElementById('fp-rule-place').value = '';
                document.getElementById('fp-rule-device').value = '';
                await rules.saveRule();
            } finally {
                window.fetch = realFetch;
            }
            return sent[0] || null;
        }"""
    )

    if body is not None:  # the save may be refused client-side, which is also fine
        assert body["place_id"] is None, "an empty select must not become id 0"
        assert body["device_id"] is None


async def test_the_cooldown_default_matches_the_api(page, base_url):
    """honesty round 3 F9: the dialog defaulted to 60, the API and CLI to 30."""
    await _open_alerts_tab(page, base_url)

    value = await page.evaluate(
        """async () => {
            const rules = await import('/static/app/alerts_rules.js');
            rules.openAddRuleDialog();
            return document.getElementById('fp-rule-cooldown').value;
        }"""
    )
    assert value == "30"

"""Round 3 Alerts tab: the rule sentence, what is still missing, the group
explainer, channel help, dry run, test sends, the summary strip, delivery log
filters and the post-"Add place" rule step."""

from __future__ import annotations

import json

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")
JSON = {"Content-Type": "application/json"}


async def _connect_webhook(page, base_url):
    res = await page.request.put(
        base_url + "/api/alerts/channels/webhook",
        data=json.dumps({"url": "http://127.0.0.1:9/hook"}),
        headers=JSON,
    )
    assert res.ok, await res.text()


async def _disconnect_all(page, base_url):
    for name in ("webhook", "telegram", "whatsapp"):
        await page.request.delete(f"{base_url}/api/alerts/channels/{name}")


async def _open_rule_dialog(page, base_url, *, open_channels=True):
    await open_alerts_tab(page, base_url, open_channels=open_channels)
    await page.click("#fp-add-rule-btn")
    await page.wait_for_selector('#fp-add-rule-dialog[data-fp-ready="true"]')


async def test_sentence_follows_the_form(page, base_url):
    await _connect_webhook(page, base_url)
    try:
        await _open_rule_dialog(page, base_url)
        sentence = page.locator("#fp-rule-sentence")
        await page.select_option("#fp-rule-place", label="Home")
        await page.select_option("#fp-rule-device", label="Ali's Keys")
        await page.uncheck("#fp-rule-on-enter")
        await page.check("#fp-rule-on-exit")
        assert await sentence.inner_text() == "Tell me on Webhook when Ali's Keys leaves Home."
        await page.check("#fp-rule-on-enter")
        text = await sentence.inner_text()
        assert text == "Tell me on Webhook when Ali's Keys arrives at or leaves Home."
        await page.uncheck("#fp-rule-channels input[data-channel=webhook]")
        assert (await sentence.inner_text()).startswith("Tell me when Ali's Keys")
    finally:
        await _disconnect_all(page, base_url)


async def test_still_needed_lists_what_save_lacks(page, base_url):
    await _connect_webhook(page, base_url)
    try:
        await _open_rule_dialog(page, base_url)
        missing = page.locator("#fp-rule-missing")
        text = await missing.inner_text()
        assert "a name" in text and "a tracker to watch" in text
        await page.fill("#fp-rule-name", "R3 needs")
        await page.select_option("#fp-rule-device", label="Ali's Keys")
        assert await missing.inner_text() == ""
    finally:
        await _disconnect_all(page, base_url)


async def test_group_choice_explains_the_quorum(page, base_url):
    await _connect_webhook(page, base_url)
    try:
        await _open_rule_dialog(page, base_url)
        await page.check("#fp-rule-target-group")
        await page.select_option("#fp-rule-group", label="Family")
        note = await page.locator("#fp-rule-group-note").inner_text()
        assert "most of its members" in note
        assert "90 minutes" in note and "left out" in note
        await page.check("#fp-rule-target-device")
        assert await page.locator("#fp-rule-group-note").is_hidden()
    finally:
        await _disconnect_all(page, base_url)


async def test_no_channel_says_why_and_offers_the_way_to_connect(page, base_url):
    await _disconnect_all(page, base_url)
    await _open_rule_dialog(page, base_url, open_channels=False)
    assert await page.locator("#fp-telegram-body").is_hidden()
    help_text = await page.locator("#fp-rule-channels-help").inner_text()
    assert "nowhere to send" in help_text
    button = page.locator("#fp-rule-connect-btn")
    await button.click()
    assert not await page.locator("#fp-add-rule-dialog").evaluate("(el) => el.open")
    assert await page.locator("#fp-telegram-body").is_visible(), "the form unfolds"
    assert await page.evaluate("document.activeElement.id") == "fp-tg-token"


async def test_dry_run_with_nothing_recorded_says_so_plainly(page, base_url):
    await _connect_webhook(page, base_url)
    try:
        await _open_rule_dialog(page, base_url)
        await page.click("#fp-rule-dryrun-btn")
        assert "Choose a tracker" in await page.locator("#fp-rule-dryrun").inner_text()
        await page.select_option("#fp-rule-device", label="Ali's Keys")
        await page.click("#fp-rule-dryrun-btn")
        await page.wait_for_function(
            "document.getElementById('fp-rule-dryrun').textContent.includes('Nothing matched')"
        )
        assert (
            "does not mean the rule is broken" in await page.locator("#fp-rule-dryrun").inner_text()
        )
    finally:
        await _disconnect_all(page, base_url)


async def test_dry_run_lists_what_would_have_been_sent(page, base_url):
    async def fake(route):
        rows = [
            {
                "observed_at": "2026-10-01T10:00:00+00:00",
                "event_type": "ENTER",
                "text": "Ali's Keys arrived at Home",
                "sends": True,
            },
            {
                "observed_at": "2026-10-01T10:05:00+00:00",
                "event_type": "EXIT",
                "text": "Ali's Keys left Home",
                "sends": False,
            },
        ]
        body = {"window_hours": 24, "rows": rows, "would_send": 1, "held_back": 1}
        await route.fulfill(json=body)

    await _connect_webhook(page, base_url)
    try:
        await page.route("**/api/alerts/rules/dry-run", fake)
        await _open_rule_dialog(page, base_url)
        await page.select_option("#fp-rule-device", label="Ali's Keys")
        await page.click("#fp-rule-dryrun-btn")
        out = page.locator("#fp-rule-dryrun")
        await out.locator("li").first.wait_for()
        text = await out.inner_text()
        assert "1 message would have been sent" in text
        assert "held back by the cooldown" in text
        assert "Find+ recorded" in text
    finally:
        await _disconnect_all(page, base_url)


async def test_test_send_reports_each_channel_plainly(page, base_url):
    async def fake(route):
        await route.fulfill(
            json={"status": "failed", "error": "HTTPSConnectionPool(host='x'): NameResolutionError"}
        )

    await _connect_webhook(page, base_url)
    try:
        await page.route("**/api/alerts/test", fake)
        await _open_rule_dialog(page, base_url)
        await page.click("#fp-rule-test-btn")
        status = page.locator("#fp-rule-test-status")
        await page.wait_for_function(
            "document.getElementById('fp-rule-test-status').textContent.includes('not sent')"
        )
        text = await status.inner_text()
        assert text.startswith("Webhook: not sent")
        assert "NameResolution" not in text and "HTTPSConnectionPool" not in text
    finally:
        await _disconnect_all(page, base_url)


async def test_webhook_section_has_its_own_test_button(page, base_url):
    await _disconnect_all(page, base_url)
    await open_alerts_tab(page, base_url)
    assert await page.locator("#fp-webhook-test").is_disabled()
    await _connect_webhook(page, base_url)

    async def sent(route):
        await route.fulfill(json={"status": "sent", "error": None})

    try:
        await page.route("**/api/alerts/test", sent)
        await open_alerts_tab(page, base_url)
        await page.click("#fp-webhook-test")
        await page.wait_for_function(
            "document.getElementById('fp-webhook-status').textContent.includes('Test message sent')"
        )
    finally:
        await _disconnect_all(page, base_url)


def _delivery(i, status="sent", channel="webhook"):
    return {
        "id": i,
        "rule_id": 1,
        "rule_name": f"Rule {i}",
        "event_kind": "device",
        "channel": channel,
        "status": status,
        "sent_at": "2026-09-20T12:00:00+00:00",
        "target": None,
        "error": None,
        "attempts": 1,
        "next_attempt_at": None,
        "text": None,
        "body": None,
    }


async def test_delivery_log_filters_and_pages(page, base_url):
    rows = [_delivery(i) for i in range(1, 21)]
    rows += [_delivery(100 + i, "failed", "telegram") for i in range(3)]

    async def fake(route):
        await route.fulfill(json=rows)

    await page.route("**/api/alerts/deliveries", fake)
    await open_alerts_tab(page, base_url)
    body = page.locator("#fp-deliveries-tbody tr")
    await body.first.wait_for()
    assert await body.count() == 15
    assert "Showing 15 of 23" in await page.locator("#fp-deliveries-count").inner_text()
    await page.click("#fp-deliveries-more")
    assert await body.count() == 23
    assert await page.locator("#fp-deliveries-more").is_hidden()
    await page.select_option("#fp-deliveries-status", "failed")
    assert await body.count() == 3
    await page.select_option("#fp-deliveries-channel", "whatsapp")
    assert await body.count() == 0
    empty = page.locator("#fp-deliveries-empty")
    assert "No deliveries match" in await empty.inner_text()
    await page.click("#fp-deliveries-clear")
    assert await body.count() == 15


async def test_telegram_steps_show_until_a_bot_is_connected(page, base_url):
    await _disconnect_all(page, base_url)
    await open_alerts_tab(page, base_url)
    steps = page.locator("#fp-tg-steps li")
    assert await steps.count() == 4
    assert "BotFather" in await steps.first.inner_text()
    assert await page.locator("#fp-tg-steps").is_visible()

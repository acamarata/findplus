"""The Alerts tab's Rules and Delivery log say so when they hold nothing.

UAT #5: the Delivery log was a bare heading over an empty table. Each list now
shows its own sentence while empty and hides it as soon as a row exists. The
shared server accumulates rules and deliveries from other tests, so the empty
case is made by answering both list routes with an empty array.
"""

from __future__ import annotations

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _empty(route):
    await route.fulfill(json=[])


async def test_empty_rules_and_deliveries_show_their_sentence(page, base_url):
    await page.route("**/api/alerts/deliveries", _empty)
    await page.route("**/api/alerts/rules", _empty)
    await open_alerts_tab(page, base_url)
    deliveries = page.locator("#fp-deliveries-empty")
    rules = page.locator("#fp-rules-empty")
    await deliveries.wait_for(state="visible")
    await rules.wait_for(state="visible")
    assert "No alerts have been sent" in await deliveries.inner_text()
    assert "No rules yet" in await rules.inner_text()


async def test_sentence_is_hidden_once_there_are_rows(page, base_url):
    await open_alerts_tab(page, base_url)
    row = {
        "id": 1,
        "rule_id": 1,
        "rule_name": "Row rule",
        "event_kind": "device",
        "channel": "webhook",
        "status": "sent",
        "sent_at": "2026-09-20 12:00:00",
    }

    async def one(route):
        await route.fulfill(json=[row])

    await page.route("**/api/alerts/deliveries", one)
    await page.evaluate(
        "import('/static/app/alerts_deliveries.js').then((m) => m.loadDeliveries())"
    )
    await page.wait_for_selector("#fp-deliveries-tbody tr")
    assert await page.locator("#fp-deliveries-empty").is_hidden()

"""Playwright browser tests for the Alerts tab's webhook channel section
(P1-E10-W7-S2-T1/T2; split from test_alerts.py, E13 loop3 L3-4).

`open_alerts_tab()` is shared across every test_alerts_* file via conftest.py.
"""

from __future__ import annotations

import json

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_remove_webhook_round_trips(page, base_url):
    """loop2 B3: removeWebhook() had the same raw-fetch bug as
    clearTelegramChannel() -- this pins the successful path actually clears
    the saved webhook, not just that the button no longer throws."""
    save = await page.request.put(
        base_url + "/api/alerts/channels/webhook",
        data=json.dumps({"url": "http://localhost:9999/hook-remove-me", "secret": None}),
        headers={"Content-Type": "application/json"},
    )
    assert save.ok, await save.text()

    await open_alerts_tab(page, base_url)
    await page.click("#fp-webhook-remove")
    await page.wait_for_function(
        """async () => {
            const r = await fetch('/api/alerts/channels');
            const body = await r.json();
            return body.webhook.configured === false;
        }"""
    )


async def test_webhook_save(page, base_url):
    """The saved URL comes back MASKED: a webhook path is a bearer credential,
    so the browser gets scheme://host plus the last few characters and never
    the routable path (security review finding 5)."""
    await open_alerts_tab(page, base_url)
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

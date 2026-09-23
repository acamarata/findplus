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


def _capture_alerts_network_and_console(page) -> tuple[list[str], list[str]]:
    """Wire console + request/response/requestfailed listeners for every
    /api/alerts* call, for test_webhook_save's CI-failure evidence trail.

    request + requestfailed, not just response: a fetch() that never reaches
    the server (aborted, network error, CSP block) fires "requestfailed"
    instead of "response" and would otherwise vanish from this evidence
    entirely.
    """
    console_events: list[str] = []
    network_events: list[str] = []
    page.on("console", lambda msg: console_events.append(f"{msg.type}: {msg.text}"))
    page.on(
        "request",
        lambda r: (
            network_events.append(f"-> {r.method} {r.url}") if "/api/alerts" in r.url else None
        ),
    )
    page.on(
        "response",
        lambda r: (
            network_events.append(f"<- {r.status} {r.request.method} {r.url}")
            if "/api/alerts" in r.url
            else None
        ),
    )
    page.on(
        "requestfailed",
        lambda r: (
            network_events.append(f"FAILED {r.method} {r.url} ({r.failure})")
            if "/api/alerts" in r.url
            else None
        ),
    )
    return console_events, network_events


async def test_webhook_save(page, base_url):
    """The saved URL comes back MASKED: a webhook path is a bearer credential,
    so the browser gets scheme://host plus the last few characters and never
    the routable path (security review finding 5).

    Order-flaky in CI (loop2-inputs.md L2-14/L3-1: `assert False is True` on
    the final `configured` check, only under full-suite load, 30x green in
    isolation). The failing assert reads server state through a fresh
    page.request.get(), not the DOM, so it cannot be explained by a client-side
    render race alone -- capture every /api/alerts* response and console
    message so the next CI failure's pytest output carries the actual
    request/response sequence instead of a bare assertion.

    Root cause (loop3, E13): open_alerts_tab() only proves #fp-telegram-section
    exists; it said nothing about alerts.js's boot-time refreshAll() (fired
    unawaited from init()) having finished its own GET /api/alerts/channels.
    Under load that GET could still be in flight when fill() ran, and if its
    render landed between fill() and click(), it overwrote #fp-webhook-url
    back to "" (renderWebhookSection did not know the field had just been
    typed into -- see the render guard added in alerts_channels.js).
    saveWebhook()'s own `if (!url) return` then made the click a silent no-op,
    which reads exactly like "the button was never wired": zero PUT requests
    reached the server. open_alerts_tab() (conftest.py) now waits for the
    data-fp-ready="alerts" marker alerts.js sets at the end of refreshAll(),
    closing the gap for this test and every other caller.
    """
    console_events, network_events = _capture_alerts_network_and_console(page)

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
    evidence = f"network={network_events!r} console={console_events!r}"
    assert channels["webhook"]["configured"] is True, evidence
    assert channels["webhook"]["url"] == "http://localhost:9999/…1234", evidence
    assert "hook-abcd" not in channels["webhook"]["url"], evidence

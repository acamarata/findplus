"""Playwright browser tests for the Alerts tab's rules surface and its
tab-level chrome (P1-E10-W7-S2-T1/T2; split from test_alerts.py, E13 loop3
L3-4 -- 425 lines split by channel/surface: telegram/webhook/deliveries moved
to their own files, this one keeps rules plus the tab-visible and latency
tests that are not channel-specific).

Seed data (cli/tests/ui/conftest.py): device "TAG-HOME" ("Home Tag"), place
"Home", group "Family" -- reused here for the add-rule dialog instead of
inserting new rows. `open_alerts_tab()` is shared across every test_alerts_*
file via conftest.py.
"""

from __future__ import annotations

import json

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_alerts_tab_visible(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector('button[data-tab="alerts"]')
    await page.click('button[data-tab="alerts"]')
    await page.wait_for_selector("#tab-alerts:not([hidden])")


async def test_alerts_latency_disclaimer_present(page, base_url):
    await open_alerts_tab(page, base_url)
    notice = page.locator("#fp-alerts-latency-notice")
    await notice.wait_for(state="visible")
    assert (
        "Alerts inherit the network's delay. An arrival or departure may be "
        "reported minutes to hours late." in await notice.inner_text()
    )


async def test_add_rule_creates_row(page, base_url):
    await open_alerts_tab(page, base_url)
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
                "channels": ["webhook"],
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert create_resp.ok, await create_resp.text()

    await open_alerts_tab(page, base_url)
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
    await open_alerts_tab(page, base_url)
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
    await open_alerts_tab(page, base_url)
    await page.wait_for_function("document.getElementById('fp-widget-map-toggle').checked === true")


async def test_the_rule_dialog_sends_null_for_an_unchosen_select(page, base_url):
    """honesty round 3 F8: Number("") is 0, and no place has id 0.

    With no places saved the select was empty, so the save posted place_id 0;
    PRAGMA foreign_keys=ON turned that into an IntegrityError and the dialog
    showed a raw 500. null is what "nothing chosen" means.
    """
    await open_alerts_tab(page, base_url)

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
    await open_alerts_tab(page, base_url)

    value = await page.evaluate(
        """async () => {
            const rules = await import('/static/app/alerts_rules.js');
            rules.openAddRuleDialog();
            return document.getElementById('fp-rule-cooldown').value;
        }"""
    )
    assert value == "30"

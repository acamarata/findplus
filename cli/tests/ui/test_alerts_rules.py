"""Playwright browser tests for the Alerts tab's rules surface and its
tab-level chrome (P1-E10-W7-S2-T1/T2; split from test_alerts.py, E13 loop3
L3-4 -- 425 lines split by channel/surface: telegram/webhook/deliveries moved
to their own files, this one keeps rules plus the tab-visible and latency
tests that are not channel-specific). The add-rule dialog's own channel-
picker behaviour (U11/U12) moved again, to test_alerts_rule_channels.py,
at the PRI rule-7 300-line file cap (UAT2 loop).

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
    # TAG-HOME carries label "Ali's Keys" (cli/tests/ui/_seed_script.py); the
    # Device select shows the label, not the raw provider name (UAT U6).
    await page.select_option("#fp-rule-device", label="Ali's Keys")
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
                # "native" needs no configured credentials (UAT2 U11's
                # server-side check); this test only checks delete.
                "channels": ["native"],
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
    # U27: the widget toggle is macOS-only and hidden without this stub
    # (window.__findplus_native, set only by the Tauri window at runtime —
    # see test_setup_wizard_native.py for the hidden-by-default coverage).
    await page.add_init_script("window.__findplus_native = true;")
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


async def test_edit_rule_prefills_and_updates_the_row(page, base_url):
    """UAT U13: Edit opens the same dialog pre-filled and PUTs, never re-POSTs
    a duplicate row; the target radios are locked since the API cannot
    retarget a rule (routes_alerts_rules.py's RuleUpdate)."""
    create_resp = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            # "native" needs no configured credentials (UAT2 U11's
            # server-side check); this test only checks Edit prefills/PUTs.
            {"name": "U13 edit rule", "device_id": "TAG-HOME", "channels": ["native"]}
        ),
        headers={"Content-Type": "application/json"},
    )
    assert create_resp.ok, await create_resp.text()
    rule_id = (await create_resp.json())["id"]

    await open_alerts_tab(page, base_url)
    row = page.locator("#fp-rules-tbody tr", has_text="U13 edit rule")
    await row.wait_for(state="visible")
    await row.get_by_text("Edit", exact=True).click()
    await page.wait_for_selector("#fp-add-rule-dialog[open]")
    assert await page.input_value("#fp-rule-name") == "U13 edit rule"
    assert await page.is_disabled("#fp-rule-target-device") is True

    await page.fill("#fp-rule-name", "U13 edit rule (renamed)")
    await page.click("#fp-rule-save")
    await page.wait_for_function("() => !document.getElementById('fp-add-rule-dialog').open")

    rules = await (await page.request.get(base_url + "/api/alerts/rules")).json()
    matching = [r for r in rules if r["id"] == rule_id]
    assert len(matching) == 1, "editing must PUT the existing row, never create a second one"
    assert matching[0]["name"] == "U13 edit rule (renamed)"


async def test_rule_actions_visible_within_pane_at_1280_and_375(page, base_url):
    """UAT3 N16: the rules table (8 cols) rendered 599px wide inside a ~348px
    side pane at 1280 and a ~307px pane at 375 -- "On exit", Channels,
    Enabled and Edit/Delete sat off-screen, reachable only by a sideways
    scroll inside the pane. The container-query card layout (matching U9's
    delivery-log fix) keeps every rule's Edit/Delete inside the pane's own
    visible box at both widths, with no horizontal scroll needed to reach them."""
    create_resp = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            {"name": "N16 visible rule", "device_id": "TAG-HOME", "channels": ["native"]}
        ),
        headers={"Content-Type": "application/json"},
    )
    assert create_resp.ok, await create_resp.text()

    for width in (1280, 375):
        await page.set_viewport_size({"width": width, "height": 900})
        await page.goto(base_url + "/")
        # Below 600px .fp-tabs (the top nav open_alerts_tab() drives) is
        # hidden by CSS in favour of the bottom .fp-tabbar -- same distinction
        # test_responsive.py's own _open_tab() makes.
        tab_selector = (
            'button[data-tab="alerts"]' if width >= 600 else '.fp-tabbar [data-tabbar-tab="alerts"]'
        )
        await page.click(tab_selector)
        await page.wait_for_selector("#fp-telegram-section")
        await page.wait_for_selector('[data-fp-ready="alerts"]')
        row = page.locator("#fp-rules-tbody tr", has_text="N16 visible rule")
        await row.wait_for(state="visible")
        await _assert_actions_and_no_overflow(page, row, width)


async def _assert_actions_and_no_overflow(page, row, width: int) -> None:
    """N16's Edit/Delete-inside-the-pane check, plus N39's no-sideways-scroll
    check. Split out of test_rule_actions_visible_within_pane_at_1280_and_375
    so that test stays under the function size cap (T1, findings queue item 1)."""
    pane_box = await page.locator("#tab-alerts").bounding_box()
    edit_box = await row.get_by_text("Edit", exact=True).bounding_box()
    delete_box = await row.get_by_text("Delete", exact=True).bounding_box()
    assert pane_box and edit_box and delete_box, f"missing box at {width}px"

    assert edit_box["x"] >= pane_box["x"] - 1, f"Edit left of the pane at {width}px"
    assert edit_box["x"] + edit_box["width"] <= pane_box["x"] + pane_box["width"] + 1, (
        f"Edit right of the pane at {width}px"
    )
    assert delete_box["x"] >= pane_box["x"] - 1, f"Delete left of the pane at {width}px"
    assert delete_box["x"] + delete_box["width"] <= pane_box["x"] + pane_box["width"] + 1, (
        f"Delete right of the pane at {width}px"
    )

    # N39: the card list itself must never be sideways-scrollable, even by
    # the couple of px a transparent WCAG touch-target halo can add with
    # nothing visibly overflowing to explain it (309px of content in a
    # 307px pane at 375).
    scroll_box = await page.evaluate(
        "() => { const s = document.getElementById('fp-rules-table')"
        ".closest('.fp-table-scroll');"
        " return {scrollWidth: s.scrollWidth, clientWidth: s.clientWidth}; }"
    )
    assert scroll_box["scrollWidth"] <= scroll_box["clientWidth"], (
        f"rules card list scrolls sideways at {width}px: "
        f"{scroll_box['scrollWidth']}px in a {scroll_box['clientWidth']}px pane"
    )


async def test_the_enabled_toggle_disables_a_rule_without_deleting_it(page, base_url):
    """UAT U13: dispatch.py already filters on `enabled` server-side -- this
    proves the dashboard's toggle reaches that same column."""
    create_resp = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            # "native" needs no configured credentials (UAT2 U11's
            # server-side check); this test only checks the enabled toggle.
            {"name": "U13 toggle rule", "device_id": "TAG-HOME", "channels": ["native"]}
        ),
        headers={"Content-Type": "application/json"},
    )
    assert create_resp.ok, await create_resp.text()
    rule_id = (await create_resp.json())["id"]

    await open_alerts_tab(page, base_url)
    row = page.locator("#fp-rules-tbody tr", has_text="U13 toggle rule")
    await row.wait_for(state="visible")
    toggle = row.locator("input[type=checkbox]")
    await toggle.wait_for(state="visible")
    assert await toggle.is_checked() is True

    await toggle.uncheck()
    await page.wait_for_function(
        """async (id) => {
            const r = await fetch('/api/alerts/rules');
            const rule = (await r.json()).find((r) => r.id === id);
            return rule && rule.enabled === false;
        }""",
        arg=rule_id,
    )

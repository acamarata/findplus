"""Dashboard 1.3, Alerts tab layout (U3, U4, U12, U31, U37).

Order is latency notice, Rules (with Add rule), Channels (one folded row each),
then the delivery log. Each rule is one compact card with an on/off switch. The
rule dialog keeps Save and Cancel in view, and its Name fills itself in.
"""

from __future__ import annotations

import json

import pytest
from axe_playwright_python.async_playwright import Axe

from ._alerts_helpers import _create_rule, open_alerts_tab, open_channel_forms
from .conftest import set_theme

pytestmark = pytest.mark.asyncio(loop_scope="session")

HOOK = {"url": "http://localhost:9999/hook-r13"}


async def _put_webhook(page, base_url):
    resp = await page.request.put(
        base_url + "/api/alerts/channels/webhook",
        data=json.dumps(HOOK),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()


async def _drop_webhook(page, base_url):
    await page.request.delete(base_url + "/api/alerts/channels/webhook")


async def _top(page, selector) -> float:
    box = await page.locator(selector).first.bounding_box()
    assert box, selector
    return box["y"]


async def test_tab_order_is_notice_rules_channels_log(page, base_url):
    await open_alerts_tab(page, base_url, open_channels=False)
    ys = [
        await _top(page, "#fp-alerts-latency-notice"),
        await _top(page, "#fp-rules-section"),
        await _top(page, "#fp-channels-section"),
        await _top(page, "#fp-deliveries-section"),
    ]
    assert ys == sorted(ys), ys
    # Add rule sits in the Rules heading row, above every channel.
    assert await _top(page, "#fp-add-rule-btn") < await _top(page, "#fp-channels-section")


async def test_channels_are_folded_rows_until_asked(page, base_url):
    await _drop_webhook(page, base_url)
    await open_alerts_tab(page, base_url, open_channels=False)
    for channel in ("telegram", "webhook", "whatsapp"):
        root = page.locator(f"#fp-{channel}-section")
        assert await root.locator("[data-channel-state]").inner_text() == "Not connected"
        toggle = root.locator("[data-channel-toggle]")
        assert (await toggle.inner_text()).strip() == "Connect"
        assert await toggle.get_attribute("aria-expanded") == "false"
        assert await page.locator(f"#fp-{channel}-body").is_hidden()
    await page.locator("#fp-webhook-section [data-channel-toggle]").click()
    assert await page.locator("#fp-webhook-body").is_visible()
    assert await page.locator("#fp-telegram-body").is_hidden()
    toggle = page.locator("#fp-webhook-section [data-channel-toggle]")
    assert (await toggle.inner_text()).strip() == "Hide"
    assert await toggle.get_attribute("aria-expanded") == "true"
    await toggle.click()
    assert await page.locator("#fp-webhook-body").is_hidden()


async def test_a_connected_channel_says_so_and_offers_edit(page, base_url):
    await _put_webhook(page, base_url)
    try:
        await open_alerts_tab(page, base_url, open_channels=False)
        root = page.locator("#fp-webhook-section")
        await page.wait_for_function(
            "document.querySelector('#fp-webhook-section [data-channel-state]')"
            ".textContent === 'Connected'"
        )
        assert (await root.locator("[data-channel-toggle]").inner_text()).strip() == "Edit"
        await root.locator("[data-channel-toggle]").click()
        assert await page.locator("#fp-webhook-remove").is_visible()
        assert await page.locator("#fp-webhook-test").is_visible()
    finally:
        await _drop_webhook(page, base_url)


async def test_each_rule_is_one_compact_card(page, base_url):
    rule_id = await _create_rule(page, base_url, "R13 card rule", ["native"])
    try:
        await open_alerts_tab(page, base_url)
        card = page.locator("#fp-rules-list .fp-rule-card", has_text="R13 card rule")
        await card.wait_for(state="visible")
        assert await page.locator("#fp-rules-table").count() == 0
        assert "Tell me" in await card.locator(".fp-rule-row-sentence").inner_text()
        switch = card.locator("input[role=switch]")
        assert await switch.is_checked()
        assert await card.get_by_text("Edit", exact=True).is_visible()
        delete = card.get_by_text("Delete", exact=True)
        assert "btn-danger" in (await delete.get_attribute("class") or "")
        box = await card.bounding_box()
        assert box and box["height"] < 130, box
    finally:
        await page.request.delete(f"{base_url}/api/alerts/rules/{rule_id}")


async def test_switch_turns_the_card_off_and_back_on(page, base_url):
    rule_id = await _create_rule(page, base_url, "R13 switch rule", ["native"])
    try:
        await open_alerts_tab(page, base_url)
        card = page.locator("#fp-rules-list .fp-rule-card", has_text="R13 switch rule")
        await card.wait_for(state="visible")
        await card.locator("input[role=switch]").uncheck()
        assert await card.get_attribute("data-enabled") == "false"
        assert await card.locator(".fp-switch-text").inner_text() == "Off"
        await card.locator("input[role=switch]").check()
        assert await card.locator(".fp-switch-text").inner_text() == "On"
    finally:
        await page.request.delete(f"{base_url}/api/alerts/rules/{rule_id}")


async def _open_new_rule_dialog(page, base_url, *, phone=False):
    await _put_webhook(page, base_url)
    if phone:  # below 600px the top tabs give way to the bottom bar
        await page.goto(base_url + "/")
        await page.wait_for_selector("#map.leaflet-container", state="attached")
        await page.click('.fp-tabbar [data-tabbar-tab="alerts"]')
        await page.wait_for_selector('[data-fp-ready="alerts"]')
    else:
        await open_alerts_tab(page, base_url, open_channels=False)
    await page.click("#fp-add-rule-btn")
    await page.wait_for_selector('#fp-add-rule-dialog[data-fp-ready="true"]')


@pytest.mark.parametrize("size", [(1400, 900), (375, 812)])
async def test_rule_dialog_footer_stays_in_view(page, base_url, size):
    width, height = size
    await page.set_viewport_size({"width": width, "height": height})
    try:
        await _open_new_rule_dialog(page, base_url, phone=width < 600)
        for selector in ("#fp-rule-save", "#fp-rule-cancel"):
            box = await page.locator(selector).bounding_box()
            assert box and box["y"] + box["height"] <= height, (selector, box)
        # Still in view after the body is scrolled to its end.
        await page.evaluate(
            "() => { const b = document.querySelector('#fp-add-rule-dialog .fp-dialog-body');"
            " b.scrollTop = b.scrollHeight; }"
        )
        box = await page.locator("#fp-rule-save").bounding_box()
        assert box and box["y"] + box["height"] <= height
    finally:
        await _drop_webhook(page, base_url)


async def test_name_fills_in_from_who_and_where(page, base_url):
    try:
        await _open_new_rule_dialog(page, base_url)
        name = page.locator("#fp-rule-name")
        assert await name.input_value() == ""
        await page.select_option("#fp-rule-place", label="Home")
        assert await name.input_value() == ""  # no tracker yet
        await page.select_option("#fp-rule-device", label="Ali's Keys")
        assert await name.input_value() == "Ali's Keys at Home"
        # Still editable and still required.
        await name.fill("Keys home")
        await page.select_option("#fp-rule-device", label="Ali's Keys")
        assert await name.input_value() == "Keys home"
        # Emptying it hands the name back on the next change, not mid-typing.
        await name.fill("")
        assert await name.input_value() == ""
        await page.select_option("#fp-rule-device", index=0)
        await page.select_option("#fp-rule-device", label="Ali's Keys")
        assert await name.input_value() == "Ali's Keys at Home"
    finally:
        await _drop_webhook(page, base_url)


async def test_editing_a_rule_keeps_its_own_name(page, base_url):
    rule_id = await _create_rule(page, base_url, "R13 keep my name", ["native"])
    try:
        await open_alerts_tab(page, base_url)
        card = page.locator("#fp-rules-list .fp-rule-card", has_text="R13 keep my name")
        await card.get_by_text("Edit", exact=True).click()
        await page.wait_for_selector('#fp-add-rule-dialog[data-fp-ready="true"]')
        await page.fill("#fp-rule-cooldown", "10")
        await page.select_option("#fp-rule-place", label="Home")
        assert await page.locator("#fp-rule-name").input_value() == "R13 keep my name"
    finally:
        await page.request.delete(f"{base_url}/api/alerts/rules/{rule_id}")


async def test_checkboxes_and_radios_share_one_size_and_colour(page, base_url):
    try:
        await _open_new_rule_dialog(page, base_url)
        sizes = await page.evaluate(
            """() => ['fp-rule-on-enter', 'fp-rule-on-exit', 'fp-rule-target-device',
                     'fp-rule-target-group'].map((id) => {
                const cs = getComputedStyle(document.getElementById(id));
                return [cs.width, cs.height, cs.accentColor];
            })"""
        )
        for width, height, accent in sizes:
            assert (width, height) == ("16px", "16px"), sizes
            assert accent != "auto", sizes
        # Both radios sit in the same two-column grid as their selects.
        device = await page.locator("#fp-rule-target-device").bounding_box()
        group = await page.locator("#fp-rule-target-group").bounding_box()
        assert device and group and abs(device["x"] - group["x"]) < 1
    finally:
        await _drop_webhook(page, base_url)


AXE = {
    "resultTypes": ["violations"],
    "runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]},
}


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 375])
async def test_cards_open_channels_and_dialog_are_axe_clean(page, base_url, theme, width):
    """Rule cards (switch on and off), every channel form unfolded, then the
    rule dialog: no serious, critical or moderate WCAG violation."""
    await _put_webhook(page, base_url)
    ids = [
        await _create_rule(page, base_url, "R13 axe on", ["webhook"]),
        await _create_rule(page, base_url, "R13 axe off", ["native"]),
    ]
    await page.request.put(
        f"{base_url}/api/alerts/rules/{ids[1]}",
        data=json.dumps({"enabled": False}),
        headers={"Content-Type": "application/json"},
    )
    try:
        await page.set_viewport_size({"width": width, "height": 800})
        await page.goto(base_url + "/")
        await page.wait_for_selector("#map.leaflet-container", state="attached")
        selector = (
            '.fp-tabbar [data-tabbar-tab="alerts"]'
            if width < 600
            else '.fp-tabs [data-tab="alerts"]'
        )
        await page.click(selector)
        await page.wait_for_selector('[data-fp-ready="alerts"]')
        await page.locator("#fp-rules-list .fp-rule-card").nth(1).wait_for()
        await set_theme(page, theme)
        await open_channel_forms(page)
        for stage in ("tab", "dialog"):
            if stage == "dialog":
                await page.click("#fp-add-rule-btn")
                await page.wait_for_selector('#fp-add-rule-dialog[data-fp-ready="true"]')
            results = await Axe().run(page, options=AXE)
            bad = [
                f"{v['impact']}: {v['id']} -> {[n.get('target') for n in v['nodes'][:3]]}"
                for v in results.response["violations"]
                if v.get("impact") in ("serious", "critical", "moderate")
            ]
            assert not bad, f"{stage} {theme} {width}: " + "; ".join(bad)
    finally:
        for rule_id in ids:
            await page.request.delete(f"{base_url}/api/alerts/rules/{rule_id}")
        await _drop_webhook(page, base_url)

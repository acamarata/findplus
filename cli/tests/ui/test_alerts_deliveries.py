"""Playwright browser tests for the Alerts tab's delivery log
(P1-E10-W7-S2-T1/T2; split from test_alerts.py, E13 loop3 L3-4).

`open_alerts_tab()` is shared across every test_alerts_* file via conftest.py.
"""

from __future__ import annotations

import json

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


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
            {"name": "Delivery log rule", "device_id": "TAG-HOME", "channels": ["webhook"]}
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

    await open_alerts_tab(page, base_url)
    await page.wait_for_selector("#fp-deliveries-table")
    headers = await page.locator("#fp-deliveries-table thead th").all_text_contents()
    assert headers == ["Rule", "Channel", "Kind", "Text", "Body", "Sent", "Status", "Error"]

    row = page.locator("#fp-deliveries-tbody tr", has_text="Delivery log rule")
    await row.wait_for(state="visible")
    cells = await row.locator("td").all_text_contents()

    assert cells[1] == "webhook"
    # text/body are rendered server-side for native rows only (notifications.md
    # §2), so a webhook row shows the empty-value placeholder in both.
    assert cells[3] == "—"
    assert cells[4] == "—"
    assert cells[6] == "failed"
    assert cells[7] == "connection refused"


@pytest.mark.parametrize(
    "viewport", [{"width": 1280, "height": 900}, {"width": 375, "height": 812}]
)
async def test_delivery_log_channel_and_kind_text_stays_inside_its_cell(
    page, base_url, ui_db, viewport
):
    """loop2 L2-6: Channel/Kind painted past their own cell into the
    neighbouring column's text at 1280 and 375 -- components.css truncated
    Text/Body/Error with an ellipsis but not these two.

    `text-overflow: ellipsis` only changes what is PAINTED, not the box model:
    a Range spanning the cell's text reports the same unclipped
    getBoundingClientRect() whether or not the rule is applied, so comparing
    rendered-text geometry to the cell's own box cannot tell the two states
    apart. `scrollWidth` (the content's real extent) vs `clientWidth` (the
    visible, fixed-by-colgroup box) is the bounding-box comparison that
    actually distinguishes them -- content wider than its box is exactly the
    condition `overflow: hidden` has to be present for, and "telegram" is
    picked as the seeded channel because it is the longest of the four values
    the column ever holds, so the overflow is real, not assumed.
    """
    import sqlite3

    rule_name = f"L2-6 rule {viewport['width']}"
    rule = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps({"name": rule_name, "device_id": "TAG-HOME", "channels": ["telegram"]}),
        headers={"Content-Type": "application/json"},
    )
    assert rule.ok, await rule.text()
    rule_id = (await rule.json())["id"]

    conn = sqlite3.connect(ui_db)
    try:
        conn.execute(
            "INSERT INTO alert_deliveries"
            " (rule_id, event_kind, event_id, channel, sent_at, status, error)"
            " VALUES (?, 'device', ?, 'telegram', '2026-09-20 12:00:00', 'sent', NULL)",
            (rule_id, 4000 + viewport["width"]),
        )
        conn.commit()
    finally:
        conn.close()

    await page.set_viewport_size(viewport)
    await page.goto(base_url + "/")
    # Below 600px .fp-tabs (button[data-tab]) is display:none and the bottom
    # .fp-tabbar takes over (components/tabbar.js) -- same split
    # test_responsive.py's _open_tab() already follows for the phone tier.
    if viewport["width"] < 600:
        await page.click('.fp-tabbar [data-tabbar-tab="alerts"]')
    else:
        await page.click('button[data-tab="alerts"]')
    await page.wait_for_selector("#fp-telegram-section")
    row = page.locator("#fp-deliveries-tbody tr", has_text=rule_name)
    await row.wait_for(state="visible")

    for index, column in ((1, "Channel"), (2, "Kind")):
        box = await page.evaluate(
            """({name, i}) => {
                const row = [...document.querySelectorAll('#fp-deliveries-tbody tr')]
                    .find((r) => r.textContent.includes(name));
                const td = row.children[i];
                const style = getComputedStyle(td);
                return {
                    overflow: style.overflow,
                    textOverflow: style.textOverflow,
                    whiteSpace: style.whiteSpace,
                    scrollWidth: td.scrollWidth,
                    clientWidth: td.clientWidth,
                };
            }""",
            {"name": rule_name, "i": index},
        )
        assert box["scrollWidth"] > box["clientWidth"], (
            f"{column} cell content ({box['scrollWidth']}px) does not exceed its box "
            f"({box['clientWidth']}px) at {viewport['width']}px -- test value too short "
            "to prove the cap actually bites"
        )
        assert box["overflow"] == "hidden", f"{column}: overflow is {box['overflow']!r}, not hidden"
        assert box["textOverflow"] == "ellipsis", (
            f"{column}: text-overflow is {box['textOverflow']!r}"
        )
        assert box["whiteSpace"] == "nowrap", f"{column}: white-space is {box['whiteSpace']!r}"

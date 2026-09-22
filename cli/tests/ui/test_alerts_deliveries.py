"""Playwright browser tests for the Alerts tab's delivery log
(P1-E10-W7-S2-T1/T2; split from test_alerts.py, E13 loop3 L3-4).

`open_alerts_tab()` is shared across every test_alerts_* file via conftest.py.
"""

from __future__ import annotations

import json

import pytest

from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _create_rule(page, base_url: str, name: str, channels: list[str]) -> int:
    """POST a rule through the real API (so the server owns it) and return its id."""
    rule = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps({"name": name, "device_id": "TAG-HOME", "channels": channels}),
        headers={"Content-Type": "application/json"},
    )
    assert rule.ok, await rule.text()
    return (await rule.json())["id"]


def _insert_delivery_rows(ui_db, statements: list[tuple[str, tuple]]) -> None:
    """Write delivery rows straight into the live sqlite file: the poller's
    dispatch pass is the only code that writes one, and these tests are
    about the view, not the dispatcher. Each entry is (sql, params)."""
    import sqlite3

    conn = sqlite3.connect(ui_db)
    try:
        for sql, params in statements:
            conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


async def test_delivery_log_shows_channel_and_status(page, base_url, ui_db):
    """CF-14: alert_deliveries rows existed since 1.0 but no UI ever read them.

    The rule is created through the API so the server owns it; the delivery row is
    written straight into the live SQLite file, because the only code that writes
    one is the poller's dispatch pass and this test is about the view, not the
    dispatcher. The assertion is on the rendered row, not the endpoint — the
    endpoint already worked and the gap was that nothing displayed it.
    """
    rule_id = await _create_rule(page, base_url, "Delivery log rule", ["webhook"])
    _insert_delivery_rows(
        ui_db,
        [
            (
                "INSERT INTO alert_deliveries"
                " (rule_id, event_kind, event_id, channel, sent_at, status, error)"
                " VALUES (?, 'device', 4242, 'webhook', '2026-09-20 12:00:00', 'failed',"
                " 'connection refused')",
                (rule_id,),
            )
        ],
    )

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
    rule_name = f"L2-6 rule {viewport['width']}"
    rule_id = await _create_rule(page, base_url, rule_name, ["telegram"])
    _insert_delivery_rows(
        ui_db,
        [
            (
                "INSERT INTO alert_deliveries"
                " (rule_id, event_kind, event_id, channel, sent_at, status, error)"
                " VALUES (?, 'device', ?, 'telegram', '2026-09-20 12:00:00', 'sent', NULL)",
                (rule_id, 4000 + viewport["width"]),
            )
        ],
    )

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
        await _assert_cell_clips_its_overflow(page, rule_name, index, column, viewport["width"])


async def _assert_cell_clips_its_overflow(
    page, rule_name: str, index: int, column: str, viewport_width: int
) -> None:
    """`scrollWidth` (the content's real extent) vs `clientWidth` (the
    visible, fixed-by-colgroup box) is the bounding-box comparison that
    actually distinguishes a clipped cell from an unclipped one -- see
    test_delivery_log_channel_and_kind_text_stays_inside_its_cell's docstring."""
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
        f"({box['clientWidth']}px) at {viewport_width}px -- test value too short "
        "to prove the cap actually bites"
    )
    assert box["overflow"] == "hidden", f"{column}: overflow is {box['overflow']!r}, not hidden"
    assert box["textOverflow"] == "ellipsis", f"{column}: text-overflow is {box['textOverflow']!r}"
    assert box["whiteSpace"] == "nowrap", f"{column}: white-space is {box['whiteSpace']!r}"


async def test_delivery_log_shows_retrying_and_failed_after_retries(page, base_url, ui_db):
    """R8: alerts_deliveries.js's statusText() renders the retry ladder state
    (retry.py MAX_ATTEMPTS=4: 1 initial send + 3 retries) -- a 'retrying' row
    names the coming attempt and when, and a 'failed' row that used up every
    retry (attempts=4) reads differently from one that never qualified for a
    retry at all (test_delivery_log_shows_channel_and_status's attempts=1
    'failed' row, unchanged)."""
    rule_id = await _create_rule(page, base_url, "Retry log rule", ["telegram"])
    _insert_delivery_rows(
        ui_db,
        [
            (
                "INSERT INTO alert_deliveries"
                " (rule_id, event_kind, event_id, channel, sent_at, status, error,"
                "  attempts, next_attempt_at)"
                " VALUES (?, 'device', 5001, 'telegram', '2026-09-20 12:00:00', 'retrying',"
                " 'timeout', 1, '2026-09-20 12:01:00')",
                (rule_id,),
            ),
            (
                "INSERT INTO alert_deliveries"
                " (rule_id, event_kind, event_id, channel, sent_at, status, error, attempts)"
                " VALUES (?, 'device', 5002, 'telegram', '2026-09-20 12:00:00', 'failed',"
                " 'timeout', 4)",
                (rule_id,),
            ),
        ],
    )

    await open_alerts_tab(page, base_url)
    await page.wait_for_selector("#fp-deliveries-table")

    rows = page.locator("#fp-deliveries-tbody tr", has_text="Retry log rule")
    await rows.first.wait_for(state="visible")
    assert await rows.count() == 2

    statuses = []
    for i in range(await rows.count()):
        cells = await rows.nth(i).locator("td").all_text_contents()
        statuses.append(cells[6])  # Status column (index per the header row above)

    retrying_status = next((s for s in statuses if s.startswith("Retrying")), None)
    assert retrying_status is not None, f"no 'Retrying' status among {statuses}"
    assert retrying_status.startswith("Retrying (attempt 2 of 4, next at ")
    assert "Failed after 4 attempts" in statuses

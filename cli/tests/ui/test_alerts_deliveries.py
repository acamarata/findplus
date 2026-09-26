"""Playwright browser tests for the Alerts tab's delivery log: headers,
channel/status rendering, the card layout and the retry ladder.
(P1-E10-W7-S2-T1/T2; split from test_alerts.py, E13 loop3 L3-4). The text/
body rendering tests (N18, UAT4 N32) moved to test_alerts_deliveries_render.py
at the PRI rule-7 300-line file cap; both files share `_create_rule`/
`_insert_delivery_rows` from `_alerts_helpers.py`.

`open_alerts_tab()` is shared across every test_alerts_* file via conftest.py.
"""

from __future__ import annotations

import pytest

from ._alerts_helpers import _create_rule, _insert_delivery_rows
from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")

#: Target (multi-target Telegram support) inserted after Channel.
_EXPECTED_HEADERS = ["Rule", "Channel", "Target", "Kind", "Text", "Body", "Sent", "Status", "Error"]


async def test_delivery_log_shows_channel_and_status(page, base_url, ui_db):
    """CF-14: alert_deliveries rows existed since 1.0 but no UI ever read them.

    The delivery row is written straight into the live SQLite file (the only
    code that normally writes one is the poller's dispatch pass, and this
    test is about the view). The rule's own channel ("native", UAT2 U11's
    server-side check needs a connected one) is unrelated to the row's own
    rendered `channel` column, set directly below.
    """
    rule_id = await _create_rule(page, base_url, "Delivery log rule", ["native"])
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
    assert headers == _EXPECTED_HEADERS

    row = page.locator("#fp-deliveries-tbody tr", has_text="Delivery log rule")
    await row.wait_for(state="visible")
    await _assert_delivery_row_cells(row)


async def _assert_delivery_row_cells(row) -> None:
    """The rendered-cell assertions for test_delivery_log_shows_channel_and_status,
    split out to keep that test under the PRI rule-7 50-line cap."""
    cells = await row.locator("td").all_text_contents()

    # UAT U22: channel/status render through the alerts.channels/statuses
    # catalogs, not the raw stored id ("webhook"/"failed").
    assert cells[1] == "Webhook"
    # Webhook has no per-target concept (migration 0011): target stays ''
    # on the row, rendered as the same dash every other "we don't know" cell
    # uses.
    assert cells[2] == "—"
    # UAT4 N32: text/body render for every channel now; event_id 4242 was
    # never seeded, so the source event is purged like a native one would
    # be, and the dash is the honest answer for any channel in that state.
    assert cells[4] == "—"
    assert cells[5] == "—"
    # UAT6 N17: this row is 'failed' but still carries a real sent_at --
    # showing "—" for it (gating Sent on status) was the exact bug the
    # finding named ("'Sent —' on a failed row that has a sent_at"). Sent
    # now reflects whether sent_at is present, not the row's current status.
    assert cells[6] != "—", cells[6]
    assert ":" in cells[6], cells[6]
    assert cells[7] == "Failed"
    # UAT6 N17: the raw exception/detail text ("connection refused") is no
    # longer shown directly -- it is mapped to a short sentence naming the
    # channel, with the raw text kept in the cell's title for power users.
    assert cells[8] != "connection refused"
    assert "Webhook" in cells[8]
    error_title = await row.locator("td").nth(8).get_attribute("title")
    assert error_title == "connection refused"


async def _open_alerts_at_viewport(page, base_url: str, viewport: dict) -> None:
    """Navigate to the dashboard at `viewport` and land on the alerts tab.

    Below 600px .fp-tabs (button[data-tab]) is display:none and the bottom
    .fp-tabbar takes over (components/tabbar.js) -- same split
    test_responsive.py's _open_tab() already follows for the phone tier.
    Split out of the two viewport-parametrized tests below so each stays
    under the function size cap (T1, findings queue item 1).
    """
    await page.set_viewport_size(viewport)
    await page.goto(base_url + "/")
    if viewport["width"] < 600:
        await page.click('.fp-tabbar [data-tabbar-tab="alerts"]')
    else:
        await page.click('button[data-tab="alerts"]')
    await page.wait_for_selector("#fp-telegram-section")


@pytest.mark.parametrize(
    "viewport", [{"width": 1280, "height": 900}, {"width": 375, "height": 812}]
)
async def test_delivery_log_is_readable_as_cards(page, base_url, ui_db, viewport):
    """UAT U9 (375px) / UAT2 U9 (1280px): the 8-column table becomes one
    labelled card per delivery instead of ellipsis-truncated, ~44px-wide
    cells, whenever its own container is narrow -- not only below a 600px
    VIEWPORT (responsive.css's original phone-tier rule) but also inside the
    ~348px-wide side pane a 1280px desktop viewport still renders it in
    (components.css's `@container (max-width: 500px)`, UAT2). Both widths
    share one assertion now: loop2 L2-6's old 1280px case asserted the
    OPPOSITE (ellipsis-clipped, not cards) before the UAT2 fix -- that
    premise no longer holds at any width this dashboard actually renders the
    log at, so there is nothing left to clip and prove.
    """
    rule_name = f"U9 card rule {viewport['width']}"
    rule_id = await _create_rule(page, base_url, rule_name, ["native"])
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

    await _open_alerts_at_viewport(page, base_url, viewport)
    row = page.locator("#fp-deliveries-tbody tr", has_text=rule_name)
    await row.wait_for(state="visible")

    _assert_card_layout(await _read_delivery_card_layout(page, rule_name))


async def _read_delivery_card_layout(page, rule_name: str) -> dict:
    """Evaluate the rendered Channel cell's card-mode layout for `rule_name`'s
    row. Split out of test_delivery_log_is_readable_as_cards so that test
    stays under the function size cap (T1, findings queue item 1)."""
    return await page.evaluate(
        """(name) => {
            const row = [...document.querySelectorAll('#fp-deliveries-tbody tr')]
                .find((r) => r.textContent.includes(name));
            const channelCell = row.children[1];
            const style = getComputedStyle(channelCell);
            const thead = document.querySelector('#fp-deliveries-table thead');
            const html = document.documentElement;
            return {
                overflowX: html.scrollWidth - html.clientWidth,
                channelLabel: channelCell.dataset.label,
                overflow: style.overflow,
                whiteSpace: style.whiteSpace,
                rowDisplay: getComputedStyle(row).display,
                theadDisplay: getComputedStyle(thead).display,
            };
        }""",
        rule_name,
    )


def _assert_card_layout(result: dict) -> None:
    """UAT U9 assertions for the 375px card layout."""
    assert result["overflowX"] <= 1, f"page scrolls horizontally: {result['overflowX']}px"
    assert result["channelLabel"] == "Channel", (
        "the card needs its own label with the header hidden"
    )
    assert result["overflow"] == "visible", (
        f"Channel cell overflow is {result['overflow']!r}, still clipping"
    )
    assert result["whiteSpace"] == "normal", f"Channel cell white-space is {result['whiteSpace']!r}"
    assert result["rowDisplay"] == "block", "a row should stack as a card, not stay a table row"
    assert result["theadDisplay"] == "none", (
        "the column headers are replaced by each td's data-label"
    )


async def test_delivery_log_shows_retrying_and_failed_after_retries(page, base_url, ui_db):
    """R8: alerts_deliveries.js's statusText() renders the retry ladder state
    (retry.py MAX_ATTEMPTS=4: 1 initial send + 3 retries) -- a 'retrying' row
    names the coming attempt and when, and a 'failed' row that used up every
    retry (attempts=4) reads differently from one that never qualified for a
    retry at all (test_delivery_log_shows_channel_and_status's attempts=1
    'failed' row, unchanged)."""
    rule_id = await _create_rule(page, base_url, "Retry log rule", ["native"])
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
        statuses.append(cells[7])  # Status column (index per the header row above)

    retrying_status = next((s for s in statuses if s.startswith("Retrying")), None)
    assert retrying_status is not None, f"no 'Retrying' status among {statuses}"
    assert retrying_status.startswith("Retrying (attempt 2 of 4, next at ")
    assert "Failed after 4 attempts" in statuses

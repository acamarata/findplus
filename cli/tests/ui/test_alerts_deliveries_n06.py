"""Playwright browser tests for UAT7 N06 (delivery log polish): Telegram
target labels, a "Skipped" reason that says why, genuinely-empty Kind/Text/
Body cells on phones, and an opened body that is never re-truncated. Split
out of test_alerts_deliveries.py to keep that file under the PRI rule-7
300-line file cap; shares `_create_rule`/`_insert_delivery_rows` from
`_alerts_helpers.py` the same way.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ._alerts_helpers import _create_rule, _insert_delivery_rows
from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_target_column_shows_the_saved_chat_label(page, base_url, ui_db, ui_env):
    """UAT7 N06: the Target column used to show a Telegram row's raw chat id
    -- it now resolves through the account's own saved target_labels, the
    same label the chip row and rule dialog already use."""
    path = Path(ui_env["FINDPLUS_STATE_DIR"]) / "alerts.json"
    path.write_text(
        json.dumps(
            {
                "channels": {
                    "telegram": {
                        "bot_token": "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678",
                        "chat_ids": ["555444333"],
                        "chat_labels": ["Family chat"],
                        "chat_title": "Test Chat",
                        "bot_username": "test_bot",
                        "captured_at": "2026-01-01T00:00:00+00:00",
                    }
                }
            }
        )
    )
    try:
        rule_id = await _create_rule(page, base_url, "N06 target label rule", ["telegram"])
        _insert_delivery_rows(
            ui_db,
            [
                (
                    "INSERT INTO alert_deliveries"
                    " (rule_id, event_kind, event_id, channel, target, sent_at, status, error)"
                    " VALUES (?, 'device', 9001, 'telegram', '555444333',"
                    " '2026-09-20 12:00:00', 'sent', NULL)",
                    (rule_id,),
                )
            ],
        )
        await open_alerts_tab(page, base_url)
        row = page.locator("#fp-deliveries-tbody tr", has_text="N06 target label rule")
        await row.wait_for(state="visible")
        cells = await row.locator("td").all_text_contents()
        assert cells[2] == "Family chat"
    finally:
        # The rules table is shared for the whole session -- a leftover
        # telegram rule here would make a LATER test's "used by N rules"
        # count (test_alerts_telegram_targets_confirm.py) wrong.
        await page.request.delete(f"{base_url}/api/alerts/rules/{rule_id}")
        path.write_text(json.dumps({"channels": {}}))


async def test_skipped_reason_says_why(page, base_url, ui_db):
    """UAT7 N06: a skipped delivery used to map "whatsapp is not configured"
    to the generic "Couldn't deliver to WhatsApp." -- indistinguishable from
    an attempted, failed send. It now reads "Skipped: WhatsApp isn't
    connected."."""
    rule_id = await _create_rule(page, base_url, "N06 skipped rule", ["native"])
    _insert_delivery_rows(
        ui_db,
        [
            (
                "INSERT INTO alert_deliveries"
                " (rule_id, event_kind, event_id, channel, sent_at, status, error)"
                " VALUES (?, 'device', 9002, 'whatsapp', '2026-09-20 12:00:00', 'skipped',"
                " 'whatsapp is not configured')",
                (rule_id,),
            )
        ],
    )
    await open_alerts_tab(page, base_url)
    row = page.locator("#fp-deliveries-tbody tr", has_text="N06 skipped rule")
    await row.wait_for(state="visible")
    cells = await row.locator("td").all_text_contents()
    assert cells[8] == "Skipped: WhatsApp isn't connected."


async def test_empty_kind_text_body_cells_are_hidden_on_phones(page, base_url, ui_db):
    """UAT7 N06: components-panels.css's phone-tier `td:empty { display:
    none }` only ever matches a genuinely empty cell -- Kind/Text/Body used
    to carry the "—" placeholder instead, so a phone card showed three blank
    labelled rows for a delivery with none of the three. event_kind is left
    NULL and event_id unseeded so Text/Body resolve to nothing either."""
    rule_id = await _create_rule(page, base_url, "N06 empty cells rule", ["native"])
    _insert_delivery_rows(
        ui_db,
        [
            (
                "INSERT INTO alert_deliveries"
                " (rule_id, event_kind, event_id, channel, sent_at, status, error)"
                " VALUES (?, NULL, 9003, 'native', '2026-09-20 12:00:00', 'sent', NULL)",
                (rule_id,),
            )
        ],
    )
    await page.set_viewport_size({"width": 375, "height": 812})
    await page.goto(base_url + "/")
    await page.click('.fp-tabbar [data-tabbar-tab="alerts"]')
    row = page.locator("#fp-deliveries-tbody tr", has_text="N06 empty cells rule")
    await row.wait_for(state="visible")
    for label in ("Kind", "Text", "Body"):
        cell = row.locator(f'td[data-label="{label}"]')
        assert await cell.count() == 1
        assert not await cell.is_visible(), f"{label} cell should be hidden when empty"


def _insert_place_event_at_1205(ui_db, home_id: int) -> int:
    """A minimal ENTER place_event (+ its observation row) for TAG-HOME at
    "Home", 12:05 -- distinct from test_alerts_deliveries_render.py's own
    0/1-minute offsets so the two files never collide on location_
    observations' (device_id, observed_at, lat, lon) UNIQUE constraint."""
    import sqlite3

    conn = sqlite3.connect(ui_db)
    try:
        obs_id = conn.execute(
            "INSERT INTO location_observations"
            " (device_id, device_name, latitude_e7, longitude_e7, observed_at,"
            "  first_fetched_at, last_fetched_at, times_returned, source, is_own_report)"
            " VALUES ('TAG-HOME', 'Home Tag', 411000000, -801000000,"
            "  '2026-09-20 12:05:00', '2026-09-20 12:05:00', '2026-09-20 12:05:00',"
            "  1, 'crowdsourced', 0)"
        ).lastrowid
        event_id = conn.execute(
            "INSERT INTO place_events"
            " (place_id, device_id, event_type, observed_at, fetched_at,"
            "  observation_id, confidence, distance_meters)"
            " VALUES (?, 'TAG-HOME', 'ENTER', '2026-09-20 12:05:00',"
            " '2026-09-20 12:05:00', ?, 'high', 0.0)",
            (home_id, obs_id),
        ).lastrowid
        conn.commit()
        return event_id
    finally:
        conn.close()


async def test_opened_body_is_not_re_truncated_at_desktop_width(page, base_url, ui_db):
    """UAT7 N06: components-panels.css truncates Text/Body/Error with
    `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` at
    desktop widths -- alerts.css's own override for an OPEN <details> must
    win so the full body is actually visible once expanded, not just present
    in the DOM behind a clipped box."""
    places = await (await page.request.get(base_url + "/api/places")).json()
    home_id = next(p["id"] for p in places if p["name"] == "Home")
    event_id = _insert_place_event_at_1205(ui_db, home_id)

    rule_id = await _create_rule(page, base_url, "N06 long body rule", ["native"])
    _insert_delivery_rows(
        ui_db,
        [
            (
                "INSERT INTO alert_deliveries"
                " (rule_id, event_kind, event_id, channel, sent_at, status, error)"
                " VALUES (?, 'device', ?, 'native', '2026-09-20 12:05:00', 'sent', NULL)",
                (rule_id, event_id),
            )
        ],
    )
    await open_alerts_tab(page, base_url)
    row = page.locator("#fp-deliveries-tbody tr", has_text="N06 long body rule")
    await row.wait_for(state="visible")
    body_cell = row.locator('td[data-label="Body"]')
    details = body_cell.locator("details")
    full_text = await details.locator("p").text_content()
    assert len(full_text) > 40, "the seeded body should be long enough to collapse"

    await details.locator("summary").click()
    await page.wait_for_function(
        """(cell) => cell.querySelector('details').open""",
        arg=await body_cell.element_handle(),
    )
    style = await body_cell.evaluate("(el) => getComputedStyle(el).whiteSpace")
    assert style == "normal", f"the open body is still clipped: white-space {style!r}"
    assert await details.locator("p").is_visible()

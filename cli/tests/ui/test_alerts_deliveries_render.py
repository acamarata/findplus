"""Playwright browser tests for the Alerts tab delivery log's rendered text
and body: a native row (UAT3 N18) and a non-native one (UAT4 N32). Split out
of test_alerts_deliveries.py at the PRI rule-7 300-line file cap; both files
share `_create_rule`/`_insert_delivery_rows` from `_alerts_helpers.py`.

`open_alerts_tab()` is shared across every test_alerts_* file via conftest.py.
"""

from __future__ import annotations

import pytest

from ._alerts_helpers import _create_rule, _insert_delivery_rows
from .conftest import open_alerts_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _insert_place_event(ui_db, home_id: int, minute: int = 0) -> int:
    """A minimal ENTER place_event (and its required observation row) for
    TAG-HOME at "Home", written straight into the live sqlite file -- the UI
    seed carries no place_events at all, and this test needs one real event
    for the server to render. Returns the new place_event id.

    `minute` offsets `observed_at` so two callers in the same test module
    (sharing the session-scoped `ui_db`) don't collide on location_
    observations' (device_id, observed_at, lat, lon) UNIQUE constraint.
    """
    import sqlite3

    now = f"2026-09-20 12:{minute:02d}:00"
    conn = sqlite3.connect(ui_db)
    try:
        obs_id = conn.execute(
            "INSERT INTO location_observations"
            " (device_id, device_name, latitude_e7, longitude_e7, observed_at,"
            "  first_fetched_at, last_fetched_at, times_returned, source, is_own_report)"
            " VALUES ('TAG-HOME', 'Home Tag', 411000000, -801000000,"
            "  ?, ?, ?, 1, 'crowdsourced', 0)",
            (now, now, now),
        ).lastrowid
        event_id = conn.execute(
            "INSERT INTO place_events"
            " (place_id, device_id, event_type, observed_at, fetched_at,"
            "  observation_id, confidence, distance_meters)"
            " VALUES (?, 'TAG-HOME', 'ENTER', ?, ?, ?, 'high', 0.0)",
            (home_id, now, now, obs_id),
        ).lastrowid
        conn.commit()
        return event_id
    finally:
        conn.close()


async def test_native_row_renders_text_with_no_channel_filter(page, base_url, ui_db):
    """UAT3 N18: the dashboard's own delivery log calls GET /api/alerts/
    deliveries with no `channel` filter at all -- rendering used to be gated
    on the REQUEST's filter equalling "native", not on the ROW's own
    channel, so this exact load (never filtered) showed the dash on every
    row, including its own Desktop notification ones.
    """
    places = await (await page.request.get(base_url + "/api/places")).json()
    home_id = next(p["id"] for p in places if p["name"] == "Home")
    event_id = _insert_place_event(ui_db, home_id)

    rule_id = await _create_rule(page, base_url, "N18 native rule", ["native"])
    _insert_delivery_rows(
        ui_db,
        [
            (
                "INSERT INTO alert_deliveries"
                " (rule_id, event_kind, event_id, channel, sent_at, status, error)"
                " VALUES (?, 'device', ?, 'native', '2026-09-20 12:00:00', 'queued', NULL)",
                (rule_id, event_id),
            )
        ],
    )

    await open_alerts_tab(page, base_url)
    row = page.locator("#fp-deliveries-tbody tr", has_text="N18 native rule")
    await row.wait_for(state="visible")
    cells = await row.locator("td").all_text_contents()
    assert cells[4] not in ("—", "")
    assert "Home" in cells[4]


async def test_non_native_row_renders_real_text_not_a_placeholder_note(page, base_url, ui_db):
    """UAT4 N32: a WhatsApp row used to say "WhatsApp sends its own message,
    not logged here" -- inaccurate, since Find+ composes the message and
    CallMeBot only relays it. The source event (event_kind, event_id) is
    exactly as renderable for whatsapp/telegram/webhook as it is for native,
    so a row with a real event now shows the same rendered text a native row
    would, not a channel-shaped placeholder.
    """
    places = await (await page.request.get(base_url + "/api/places")).json()
    home_id = next(p["id"] for p in places if p["name"] == "Home")
    event_id = _insert_place_event(ui_db, home_id, minute=1)

    rule_id = await _create_rule(page, base_url, "N32 whatsapp rule", ["native"])
    _insert_delivery_rows(
        ui_db,
        [
            (
                "INSERT INTO alert_deliveries"
                " (rule_id, event_kind, event_id, channel, sent_at, status, error)"
                " VALUES (?, 'device', ?, 'whatsapp', '2026-09-20 12:00:00', 'sent', NULL)",
                (rule_id, event_id),
            )
        ],
    )

    await open_alerts_tab(page, base_url)
    row = page.locator("#fp-deliveries-tbody tr", has_text="N32 whatsapp rule")
    await row.wait_for(state="visible")
    cells = await row.locator("td").all_text_contents()
    assert cells[1] == "WhatsApp"
    assert "Home" in cells[4]
    assert "sends its own message" not in cells[4]
    assert "sends its own message" not in cells[5]

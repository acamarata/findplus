"""Shared helpers for the Alerts tab's test_alerts_*.py files (split from
ui/conftest.py, E13 stage 2, size cap; originally split from test_alerts.py
in loop3 L3-4). `_create_rule`/`_insert_delivery_rows` joined the navigation
helper here (UAT4 N32) so test_alerts_deliveries.py and
test_alerts_deliveries_render.py, split from it at the PRI rule-7 300-line
cap, share one definition instead of two.

Purpose    : Navigate to `/` and switch to the Alerts tab, waiting for
             alerts.js's own init() to finish wiring handlers; create a rule
             through the real API; write delivery rows straight into the
             live sqlite file (the poller's dispatch pass is the only code
             that writes one, and these tests are about the view).
Inputs     : `page` (Playwright Page), `base_url` (str), `ui_db` (Path).
Outputs    : None (navigation) / a rule id / None (delivery rows written).
Constraints: Plain functions, not fixtures -- `open_alerts_tab` is
             re-exported from `conftest.py` so `from .conftest import
             open_alerts_tab` keeps working for every file that already
             imports it that way.
"""

from __future__ import annotations

import json
import sqlite3


async def open_alerts_tab(page, base_url) -> None:
    """Navigate to `/` and switch to the Alerts tab; shared by every
    test_alerts_*.py file (split from test_alerts.py, E13 loop3 L3-4).

    #fp-telegram-section is static markup, present at first paint (R-P2-20):
    it says nothing about whether alerts.js's init() has run yet. main.js's
    boot chain (main() -> bootDashboard() -> alerts.js init()) has no
    top-level `await`, so page.goto()'s 'load' wait does not cover it either
    -- a click right after this helper returns can land before
    wireStaticControls() has wired #fp-add-rule-btn/#fp-webhook-save/etc., or
    while the boot-time refreshAll() is still in flight and about to stomp
    whatever the test just typed or set (E13 loop3, CI 35560066419: three
    independent timeouts/assertion failures across test_alerts_rules.py,
    test_alerts_telegram.py and test_alerts_webhook.py, all through this one
    helper). alerts.js sets data-fp-ready once its init() -- wiring included
    -- has fully run; waiting for it here closes the gap for every caller.

    The tab-switch click itself has the same class of race, one step earlier:
    main() calls initTabbar() (wires every button[data-tab] click) and only
    then, synchronously, initMap() -- which makes Leaflet stamp "leaflet-
    container" onto #map -- before it goes on to wire anything else. A click
    on the tab button that lands before initTabbar() has run is silently a
    no-op: the page stays on whichever tab was already active, alerts.js's
    init() still runs (nothing gates it on the tab), so data-fp-ready gets
    set regardless, and #fp-telegram-section sits there ready but hidden --
    the exact shape of the full-lane timeout this helper hit under load
    (2026-09-23 bisection). Waiting for #map.leaflet-container first proves
    initTabbar() already ran, since it is the previous synchronous line.
    """
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container", state="attached")
    await page.click('button[data-tab="alerts"]')
    await page.wait_for_selector("#fp-telegram-section")
    await page.wait_for_selector('[data-fp-ready="alerts"]')


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
    conn = sqlite3.connect(ui_db)
    try:
        for sql, params in statements:
            conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()

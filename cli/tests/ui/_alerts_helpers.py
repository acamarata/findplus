"""The Alerts-tab navigation helper shared by every test_alerts_*.py file
(split from ui/conftest.py, E13 stage 2, size cap; originally split from
test_alerts.py in loop3 L3-4).

Purpose    : Navigate to `/` and switch to the Alerts tab, waiting for
             alerts.js's own init() to finish wiring handlers.
Inputs     : `page` (Playwright Page), `base_url` (str).
Outputs    : None -- the page is left on the Alerts tab, ready.
Constraints: Plain async function, not a fixture -- re-exported from
             `conftest.py` so `from .conftest import open_alerts_tab` keeps
             working for every file that already imports it that way.
"""

from __future__ import annotations


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

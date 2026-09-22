"""Keyboard navigation for the `.fp-tabs` tablist (UAT U31).

Purpose    : Before this fix the tabs ignored arrow keys entirely and every
             map marker/path was its own Tab stop ahead of the timeline. This
             covers the WAI-ARIA roving-tabindex pattern (main.js's
             switchTab() + components/tabs_a11y.js's wireTabsKeyboard()) and
             confirms Leaflet's markers/polylines opted out of the Tab order
             (map.js's `keyboard: false`).
Constraints: Same session-scoped `live_server` as every other file here.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _tabs(page):
    return await page.eval_on_selector_all(
        ".fp-tabs .fp-tab",
        "els => els.map(e => ({tab: e.dataset.tab, selected: e.getAttribute('aria-selected'), "
        "tabindex: e.tabIndex}))",
    )


async def test_only_the_active_tab_is_a_tab_stop(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")
    tabs = await _tabs(page)
    assert [t["tab"] for t in tabs] == ["dashboard", "places", "groups", "alerts"]
    assert tabs[0]["selected"] == "true" and tabs[0]["tabindex"] == 0
    for t in tabs[1:]:
        assert t["selected"] == "false" and t["tabindex"] == -1


async def test_arrow_right_moves_focus_and_activates_the_next_tab(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")
    await page.focus('.fp-tabs [data-tab="dashboard"]')
    await page.keyboard.press("ArrowRight")
    await page.wait_for_selector("#tab-places:not([hidden])")
    focused = await page.evaluate("document.activeElement.dataset.tab")
    assert focused == "places"
    tabs = await _tabs(page)
    assert next(t for t in tabs if t["tab"] == "places")["selected"] == "true"


async def test_arrow_left_wraps_to_the_last_tab(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")
    await page.focus('.fp-tabs [data-tab="dashboard"]')
    await page.keyboard.press("ArrowLeft")
    await page.wait_for_selector("#tab-alerts:not([hidden])")
    focused = await page.evaluate("document.activeElement.dataset.tab")
    assert focused == "alerts"


async def test_end_key_jumps_to_the_last_tab(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")
    await page.focus('.fp-tabs [data-tab="dashboard"]')
    await page.keyboard.press("End")
    focused = await page.evaluate("document.activeElement.dataset.tab")
    assert focused == "alerts"
    await page.wait_for_selector("#tab-alerts:not([hidden])")


async def test_map_markers_and_paths_are_not_tab_stops(page, base_url):
    """map.js creates every marker/polyline with `keyboard: false`; Leaflet
    then never adds a tabindex to their DOM elements."""
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")
    await page.wait_for_timeout(300)  # let renderMap() finish drawing today's track, if any

    focusable_map_children = await page.eval_on_selector_all(
        "#map [tabindex]:not(.leaflet-control-zoom-in):not(.leaflet-control-zoom-out)",
        "els => els.length",
    )
    assert focusable_map_children == 0

"""Dashboard chrome from UAT walk 6/7: controls width, tab bar scroll, banner,
footer, status dot.

Purpose    : Pin the WP-D/E fixes. A long tracker name used to widen the page
             to 517px at 375 (N09) and push Export onto a second row at 1280;
             a tab-bar tap left the page at scrollY 0 (N10); the banner printed
             raw status codes while the service dot stayed green (N06); the
             footer never said Find+ is not affiliated (N08). UAT7-N20: the
             dot's state (idle/live/stale/warn) was colour- and title-only,
             with no accessible name at all.
Inputs     : live_server (conftest.py) and its ui_db, which this file writes
             one poll_runs row into and removes again.
Outputs    : Assertions only.
Constraints: Every test restores what it changed (the TAG-AWAY name, the poll
             run), so the session server stays as the rest of the suite expects.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from findplus import honesty

pytestmark = pytest.mark.asyncio(loop_scope="session")

LONG_NAME = "Grandma's very long named Bluetooth tracker tag in the car glovebox"


def _set_away_name(ui_db, name):
    """A provider-side name (labels cap at 40 characters; provider names don't)."""
    conn = sqlite3.connect(ui_db)
    try:
        conn.execute("UPDATE devices SET name = ? WHERE device_id = 'TAG-AWAY'", (name,))
        conn.commit()
    finally:
        conn.close()


async def _boot(page, base_url, width, height):
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]", timeout=20000)


@pytest.mark.parametrize(("width", "height"), ((375, 812), (1280, 800)))
async def test_a_long_tracker_name_never_widens_the_controls(page, base_url, ui_db, width, height):
    _set_away_name(ui_db, LONG_NAME)
    try:
        await _boot(page, base_url, width, height)
        await page.wait_for_selector("#device-filter option[value='TAG-AWAY']", state="attached")
        layout = await page.evaluate(
            """() => ({
                scroll: document.documentElement.scrollWidth,
                filter: document.getElementById('device-filter').getBoundingClientRect().top,
                exportBtn: document.getElementById('btn-export').getBoundingClientRect().top,
                option: document.querySelector("#device-filter [value='TAG-AWAY']").textContent,
            })"""
        )
    finally:
        _set_away_name(ui_db, "Away Tag")
    assert layout["scroll"] == width, f"page scrolls to {layout['scroll']}px at {width}px"
    assert layout["option"].startswith("Grandma's very long named") and "…" in layout["option"]
    if width == 1280:
        assert abs(layout["exportBtn"] - layout["filter"]) < 8, "Export wrapped to a second row"


async def test_a_tab_bar_tap_brings_its_pane_into_view(page, base_url):
    await _boot(page, base_url, 375, 812)
    await page.click('.fp-tabbar [data-tabbar-tab="alerts"]')
    await page.wait_for_selector("#tab-alerts:not([hidden])")
    state = await page.evaluate(
        """() => ({
            y: window.scrollY,
            paneTop: document.getElementById('timeline-pane').getBoundingClientRect().top,
        })"""
    )
    assert state["y"] > 0, "the tap left the page at the top"
    assert state["paneTop"] < 812 - 56, "the Alerts pane is still below the fold"
    await page.click('.fp-tabbar [data-tabbar-tab="dashboard"]')
    assert await page.evaluate("window.scrollY") == 0


async def test_the_footer_says_find_plus_is_not_affiliated(page, base_url):
    await _boot(page, base_url, 1280, 800)
    footer = page.locator("#fp-footer-not-affiliated")
    await page.wait_for_function(
        "() => document.getElementById('fp-footer-not-affiliated').textContent !== ''"
    )
    assert await footer.text_content() == honesty.NOT_AFFILIATED


async def test_status_dot_has_an_accessible_name_matching_its_state(page, base_url):
    """UAT7-N20: role="img" plus an aria-label equal to the title text, so
    the dot's state reaches screen readers and touch users, not just a mouse
    hovering for the tooltip."""
    await _boot(page, base_url, 1280, 800)
    dot = page.locator("#live-dot")
    await page.wait_for_function(
        "() => document.getElementById('live-dot').hasAttribute('data-health')"
    )
    role = await dot.get_attribute("role")
    title = await dot.get_attribute("title")
    label = await dot.get_attribute("aria-label")
    assert role == "img"
    assert title, "the dot has no title to derive an accessible name from"
    assert label == title


async def test_a_failed_poll_reads_as_words_with_an_in_app_fix(page, base_url, ui_db):
    """N06: no status code on screen, a sign-in action, and an amber dot.
    UAT7-N20: the amber dot's aria-label tracks the same change."""
    conn = sqlite3.connect(ui_db)
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    cur = conn.execute(
        "INSERT INTO poll_runs (device_id, started_at, finished_at, status, observations_returned,"
        " observations_new, error_type, error_message)"
        " VALUES ('TAG-HOME', ?, ?, 'provider_unauthenticated', 0, 0, 'unauthenticated',"
        " 'provider not authenticated')",
        (now, now),
    )
    conn.commit()
    try:
        await _boot(page, base_url, 1280, 800)
        banner = await page.inner_text("#alert")
        card = await page.inner_text("#card-poll-status")
        health = await page.get_attribute("#live-dot", "data-health")
        dot_title = await page.get_attribute("#live-dot", "title")
        dot_label = await page.get_attribute("#live-dot", "aria-label")
        action = page.locator("#alert .alert-action")
        assert await action.inner_text() == "Connect an account"
        await action.click()
        await page.wait_for_selector("#settings-modal:not(.hidden)")
    finally:
        conn.execute("DELETE FROM poll_runs WHERE id = ?", (cur.lastrowid,))
        conn.commit()
        conn.close()
    for text in (banner, card):
        assert "provider_unauthenticated" not in text and "not authenticated" not in text
    assert "Google Find Hub" in banner
    assert card == "last attempt: not signed in"
    assert health == "warn", "the dot stayed green while the last poll failed"
    assert dot_label == dot_title, "the dot's accessible name did not update with its state"

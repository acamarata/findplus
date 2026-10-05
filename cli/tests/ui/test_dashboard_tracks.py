"""Tracker blocks fold, hour headings appear, and a refresh keeps the user's place.

Round 3 (dash3): with many trackers the pane was one endless column, and every
live refresh redrew the list (losing the selected row and scroll) and re-fitted
the map. These tests drive a synthetic busy day through the real dashboard.
"""

# ruff: noqa: E501  (inline JS one-liners and fixture rows read better unwrapped)

from __future__ import annotations

import pytest

from ._many_tracks import install_busy_day, settle_map

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _boot(page, base_url, **kw):
    holder = await install_busy_day(page, **kw)
    await page.goto(base_url + "/")
    await page.wait_for_selector("#tracks .track-block")
    await settle_map(page)
    return holder


async def _reload_day(page):
    await page.evaluate(
        "() => import('/static/app/timeline.js').then((m) => m.loadDay(window.__day || document.getElementById('day-picker').value))"
    )


async def test_many_trackers_start_folded_except_the_first(page, base_url):
    await _boot(page, base_url)
    toggles = page.locator(".track-toggle")
    assert await toggles.count() == 6
    states = [await toggles.nth(i).get_attribute("aria-expanded") for i in range(6)]
    assert states == ["true"] + ["false"] * 5
    # Folded rows are hidden and are not keyboard stops.
    visible_rows = await page.locator(".tl-item:visible").count()
    assert visible_rows == 12


async def test_toggle_and_show_all(page, base_url):
    await _boot(page, base_url)
    await page.locator(".track-toggle").nth(2).click()
    assert await page.locator(".tl-item:visible").count() == 24
    await page.get_by_role("button", name="Show all").click()
    assert await page.locator(".tl-item:visible").count() == 72
    await page.get_by_role("button", name="Hide all").click()
    assert await page.locator(".tl-item:visible").count() == 0


async def test_few_trackers_all_open_and_no_fold_all_row(page, base_url):
    await _boot(page, base_url, tracks=2)
    assert await page.locator(".track-toggle[aria-expanded='false']").count() == 0
    assert await page.locator(".track-foldall").count() == 0


async def test_map_click_unfolds_the_row(page, base_url):
    await _boot(page, base_url)
    await page.evaluate(
        "() => import('/static/app/timeline.js').then((m) => m.selectPoint(5001, false))"
    )
    assert await page.locator(".track-toggle").nth(5).get_attribute("aria-expanded") == "true"
    assert await page.locator('.tl-item[data-id="5001"].selected').is_visible()


async def test_hour_headings_and_ago_and_rough_fix(page, base_url):
    await _boot(page, base_url)
    assert await page.locator(".track-block").first.locator(".tl-hour").count() >= 1
    assert await page.locator(".tl-ago").count() == 6  # the newest row of each tracker
    assert await page.locator(".tl-ago:visible").count() == 1  # only the open block shows it
    assert "rough fix" in await page.locator(".track-block").first.inner_text()


async def test_refresh_with_same_data_redraws_nothing(page, base_url):
    await _boot(page, base_url)
    await page.evaluate(
        "() => { document.querySelector('#tracks').dataset.mark = '1'; window.__first = document.querySelector('.track-block'); }"
    )
    await _reload_day(page)
    same = await page.evaluate("() => window.__first === document.querySelector('.track-block')")
    assert same, "an identical refresh must not rebuild the list"


async def test_refresh_with_new_point_keeps_selection_and_map_view(page, base_url):
    holder = await _boot(page, base_url)
    await page.evaluate(
        "() => import('/static/app/timeline.js').then((m) => m.selectPoint(1003, false))"
    )
    await page.evaluate(
        "() => window.__zoom = (document.querySelector('#map').dataset.z = 'x', null)"
    )
    await page.evaluate(
        "() => import('/static/app/state.js').then((m) => m.state.map.setZoom(9, { animate: false }))"
    )
    body = holder["body"]
    body["tracks"][0]["points"].append(
        {**body["tracks"][0]["points"][-1], "id": 9999, "sequence": 13}
    )
    await _reload_day(page)
    await page.wait_for_selector('.tl-item[data-id="9999"]', state="attached")
    assert await page.locator('.tl-item[data-id="1003"].selected').count() == 1
    zoom = await page.evaluate(
        "() => import('/static/app/state.js').then((m) => m.state.map.getZoom())"
    )
    assert zoom == 9, "a refresh must not re-fit the map the user has zoomed"

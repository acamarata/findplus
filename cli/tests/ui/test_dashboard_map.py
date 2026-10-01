"""Map legend, decluttering and the tile-failure note (round 3, dash3)."""

# ruff: noqa: E501
from __future__ import annotations

import pytest

from ._many_tracks import install_busy_day

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _boot(page, base_url, **kw):
    await install_busy_day(page, **kw)
    await page.goto(base_url + "/")
    await page.wait_for_selector("#tracks .track-block")


async def test_legend_lists_each_tracker_and_frames_it(page, base_url):
    await _boot(page, base_url)
    rows = page.locator(".map-legend button")
    assert await rows.count() == 6
    assert "Busy Tag 3" in await rows.nth(3).inner_text()
    before = await page.evaluate(
        "() => import('/static/app/state.js').then((m) => m.state.map.getBounds().toBBoxString())"
    )
    await rows.nth(3).click()
    after = await page.evaluate(
        "() => import('/static/app/state.js').then((m) => m.state.map.getBounds().toBBoxString())"
    )
    assert before != after


async def test_no_legend_for_a_single_tracker(page, base_url):
    await _boot(page, base_url, tracks=1)
    assert await page.locator(".map-legend").count() == 0


async def test_dense_map_shrinks_middle_markers_until_zoomed_in(page, base_url):
    await _boot(page, base_url)
    assert await page.locator("#map.map--dense").count() == 1
    await page.evaluate(
        "() => import('/static/app/state.js').then((m) => m.state.map.setZoom(16, { animate: false }))"
    )
    assert await page.locator("#map.map--dense").count() == 0


async def test_small_map_is_not_dense(page, base_url):
    await _boot(page, base_url, tracks=2, points=5)
    assert await page.locator("#map.map--dense").count() == 0


async def test_map_has_an_accessible_name(page, base_url):
    await _boot(page, base_url)
    assert await page.locator("#map").get_attribute("aria-label") == "Map of tracker locations"


async def test_failed_tiles_show_an_offline_note(page, base_url):
    await page.route("https://tile.openstreetmap.org/**", lambda r: r.abort())
    await _boot(page, base_url)
    note = page.locator("#map-tiles-note")
    await note.wait_for(state="visible")
    assert "may be offline" in await note.inner_text()
    # The data is still drawn.
    assert await page.locator(".leaflet-marker-icon").count() > 0

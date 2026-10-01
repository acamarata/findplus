"""Devices dialog: search, sort, count, last-seen text, bulk buttons on what shows.

Round 3 (dash3). Nothing here saves, so the shared seed (four devices, three
tracked, TAG-STALE with no location) is left alone.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")
    await page.wait_for_selector('button[data-tab="places"]')
    await page.click("#btn-devices")
    await page.wait_for_selector("#device-modal:not(.hidden)")
    await page.wait_for_selector(".device-row")


async def _visible_ids(page):
    return await page.evaluate(
        "() => [...document.querySelectorAll('#device-list .device-row')].filter((r) => !r.hidden).map((r) => r.dataset.deviceId)"
    )


async def test_rows_say_when_each_tracker_was_last_seen(page, base_url):
    await _open(page, base_url)
    home = page.locator('.device-row[data-device-id="TAG-HOME"] .d-seen')
    assert "Last seen" in await home.inner_text()
    stale = page.locator('.device-row[data-device-id="TAG-STALE"] .d-seen')
    assert await stale.inner_text() == "No location yet"


async def test_search_filters_by_name_label_and_id(page, base_url):
    await _open(page, base_url)
    search = page.get_by_label("Search trackers")
    await search.fill("away")
    assert await _visible_ids(page) == ["TAG-AWAY"]
    assert "Showing 1 of" in await page.locator(".device-count").inner_text()
    await search.fill("ali's keys")  # the label, not the raw name
    assert await _visible_ids(page) == ["TAG-HOME"]
    await search.fill("tag-stale")
    assert await _visible_ids(page) == ["TAG-STALE"]
    await search.fill("zzz")
    assert await _visible_ids(page) == []
    assert "No tracker matches" in await page.locator(".device-none").inner_text()
    await search.fill("")
    assert len(await _visible_ids(page)) >= 4


async def test_track_none_only_touches_the_rows_showing(page, base_url):
    await _open(page, base_url)
    await page.get_by_label("Search trackers").fill("away")
    await page.click("#btn-track-none")
    assert not await page.is_checked("#chk-TAG-AWAY")
    assert await page.is_checked("#chk-TAG-HOME")  # hidden by the search, untouched


async def test_sort_by_last_seen_puts_never_seen_last(page, base_url):
    await _open(page, base_url)
    await page.get_by_label("Sort trackers").select_option("seen")
    ids = await _visible_ids(page)
    assert ids.index("TAG-HOME") < ids.index("TAG-STALE")
    assert ids.index("TAG-AWAY") < ids.index("TAG-STALE")


async def test_sort_keeps_unsaved_ticks(page, base_url):
    await _open(page, base_url)
    await page.uncheck("#chk-TAG-AWAY")
    await page.get_by_label("Sort trackers").select_option("name")
    assert not await page.is_checked("#chk-TAG-AWAY")

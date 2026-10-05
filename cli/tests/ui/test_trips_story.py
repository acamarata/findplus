"""The day story: stays and trips as rows, folded home noise, selection, keyboard, states."""

# ruff: noqa: E501

from __future__ import annotations

import pytest

from ._trips_helpers import open_day

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _titles(page):
    await page.wait_for_selector(".story-item")
    return await page.locator(".story-title").all_inner_texts()


async def test_school_run_reads_as_a_story(trips_page, trips_server):
    await open_day(trips_page, trips_server, "school")
    assert await _titles(trips_page) == ["Home", "Trip to School", "School", "Trip to Home", "Home"]
    trip = trips_page.locator(".story-item[data-kind=trip]").first
    text = await trip.inner_text()
    assert "7:42 AM to 8:02 AM" in text and "(approximate)" in text and "6 sightings" in text
    assert (
        "31 sightings" in await trips_page.locator(".story-item[data-kind=stay]").first.inner_text()
    )
    assert await trips_page.locator(".tl-item").count() == 0, (
        "the raw rows are not drawn in the story"
    )
    assert "worked out from sparse" in await trips_page.locator(".story-honesty").inner_text()


async def test_map_draws_trips_not_home_pins(trips_page, trips_server):
    await open_day(trips_page, trips_server, "school")
    await trips_page.wait_for_selector(".story-item")
    assert await trips_page.locator(".marker-num").count() == 0
    dashed = await trips_page.locator("#map path[stroke-dasharray='9 8']").count()
    assert dashed == 2, "one dashed (approximate) line per trip"
    assert await trips_page.locator(".story-arrow").count() >= 4


async def test_home_noise_day_is_one_line(trips_page, trips_server):
    await open_day(trips_page, trips_server, "noise")
    assert await _titles(trips_page) == ["Home"]
    assert await trips_page.locator(".story-item[data-kind=trip]").count() == 0
    assert "sightings" in await trips_page.locator(".story-item").inner_text()
    assert await trips_page.locator(".marker-num").count() == 0
    await trips_page.check("#story-inside")
    assert await trips_page.locator("#map path.leaflet-interactive").count() > 30


async def test_gap_day_has_silent_trip_and_stray(trips_page, trips_server):
    await open_day(trips_page, trips_server, "gap")
    assert await _titles(trips_page) == ["Home", "Trip to Grandma's", "Grandma's"]
    assert (
        "no sightings along the way"
        in await trips_page.locator(".story-item[data-kind=trip]").inner_text()
    )
    assert "1 stray fix" in await trips_page.locator(".story-stray").inner_text()


async def test_switch_to_raw_and_back(trips_page, trips_server):
    await open_day(trips_page, trips_server, "school")
    await trips_page.wait_for_selector(".story-item")
    await trips_page.click("#fp-latest-focus [data-view=raw]")
    await trips_page.wait_for_selector(".tl-item")
    assert await trips_page.locator("#story").is_hidden()
    assert await trips_page.locator(".marker-num").count() > 0
    assert (
        await trips_page.get_attribute("#fp-latest-focus [data-view=raw]", "aria-pressed") == "true"
    )
    await trips_page.click("#fp-latest-focus [data-view=story]")
    await trips_page.wait_for_selector(".story-item")
    assert await trips_page.locator(".tl-item").count() == 0


async def test_click_and_keyboard_focus_the_map(trips_page, trips_server):
    await open_day(trips_page, trips_server, "school")
    await trips_page.wait_for_selector(".story-item")
    first = trips_page.locator(".story-item").first
    await first.focus()
    await trips_page.keyboard.press("ArrowDown")
    assert await trips_page.evaluate("document.activeElement.dataset.kind") == "trip"
    await trips_page.keyboard.press("Enter")
    assert await trips_page.locator(".story-item.is-picked[aria-current=true]").count() == 1
    assert await trips_page.locator("#map .leaflet-interactive").count() > 0
    assert await trips_page.locator(".strip-bar rect.is-picked").count() == 1
    await trips_page.keyboard.press("Escape")
    assert await trips_page.locator(".story-item.is-picked").count() == 0


async def test_empty_and_sparse_days(trips_page, trips_server):
    await open_day(trips_page, trips_server, "empty", prefs={"findplus.dayView": "story"})
    await trips_page.get_by_text("No sightings on this day").first.wait_for()
    await trips_page.evaluate(
        f"import('/static/app/timeline.js').then(m => m.loadDay('{trips_server['days']['single']}'))"
    )
    await trips_page.get_by_text("Too few sightings for a story").wait_for()
    await trips_page.click("#story .btn")
    await trips_page.wait_for_selector(".tl-item")


async def test_error_retry_and_offline(trips_page, trips_server):
    state = {"mode": "fail"}

    async def trips_route(route):
        if state["mode"] == "fail":
            await route.fulfill(status=500, json={"detail": "boom"})
        elif state["mode"] == "offline":
            await route.abort()
        else:
            await route.continue_()

    await trips_page.route("**/api/trips?*", trips_route)
    await open_day(trips_page, trips_server, "school", prefs={"findplus.dayView": "story"})
    await trips_page.get_by_text("Could not load the day story").wait_for()
    state["mode"] = "ok"
    await trips_page.get_by_role("button", name="Retry").click()
    await trips_page.wait_for_selector(".story-item")
    state["mode"] = "offline"
    await trips_page.click("#btn-prev-day")
    await trips_page.get_by_text("Find+ is not responding").wait_for()

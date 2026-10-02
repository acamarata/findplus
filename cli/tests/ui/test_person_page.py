"""The Person page: header, date bar, summary, map, lanes, trackers, keyboard."""

from __future__ import annotations

import pytest

from ._offline_tiles import stub_osm_tiles
from ._person_helpers import (
    ALERTS_LATENCY,
    HONESTY_TRIPS,
    PRESENCE_STALE,
    ensure_person,
    open_person,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def pid(trips_server):
    return ensure_person(trips_server)


async def test_page_draws_every_part(trips_page, trips_server, pid):
    day = await open_person(trips_page, trips_server, pid)
    p = trips_page
    assert await p.locator("#tab-person").is_visible()
    assert (await p.inner_text(".person-name")).startswith("Sam")
    assert await p.locator("#person-now").inner_text()
    assert await p.locator(".person-conf").count() == 1
    assert await p.input_value("#person-date") == day
    assert await p.locator(".person-line-btn").count() == 5
    assert await p.inner_text(".person-summary h3") == "Sam's day"
    assert "Seen by shoes and bag" in await p.locator(".person-line-btn").first.inner_text()
    assert "53 sightings" in await p.locator(".person-tracker", has_text="Sam").first.inner_text()
    assert await p.locator(".lane").count() == 2, "one lane per tracker"
    assert await p.locator(".person-tracker").count() == 2
    body = await p.inner_text("#person-body")
    assert HONESTY_TRIPS in body and ALERTS_LATENCY in body and PRESENCE_STALE in body
    assert "role." not in body, "no raw catalog keys on screen"


async def test_map_has_one_line_per_tracker(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    lines = await trips_page.locator("#map path[stroke-dasharray='6 5']").count()
    assert lines == 2, "one polyline per tracker, never merged"
    assert await trips_page.locator(".marker-num").count() == 0, (
        "the dashboard's own markers are gone"
    )


async def test_map_is_named_for_the_person_and_renamed_on_leaving(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    assert await p.get_attribute("#map", "aria-label") == "Map of Sam's day, one line per tracker"
    await p.click("#person-back")
    await p.wait_for_selector("#tab-dashboard", state="visible")
    assert "Sam" not in await p.get_attribute("#map", "aria-label")


async def test_lead_tracker_is_first(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    first = trips_page.locator(".lane-name").first
    now = await trips_page.evaluate(f"fetch('/api/people/{pid}/now').then(r => r.json())")
    names = await trips_page.locator(".lane-name").all_inner_texts()
    assert len(names) == 2
    chip = trips_page.locator(".person-chip--lead")
    if now["lead_device_id"]:
        assert await chip.count() == 1
        assert (await first.inner_text()) in (await chip.locator("xpath=ancestor::li").inner_text())


async def test_date_bar_arrows_picker_today_and_keys(trips_page, trips_server, pid):
    day = await open_person(trips_page, trips_server, pid)
    p = trips_page
    await p.click("#person-prev")
    await p.wait_for_function(f"document.querySelector('#person-date').value < '{day}'")
    await p.click("#person-next")
    await p.wait_for_function(f"location.hash.includes('{day}')")
    await p.keyboard.press("ArrowLeft")
    await p.wait_for_function(f"!location.hash.includes('{day}')")
    await p.fill("#person-date", day)
    await p.dispatch_event("#person-date", "change")
    await p.wait_for_function(f"location.hash.includes('{day}')")
    await p.click("#person-today")
    await p.wait_for_function(f"!location.hash.includes('{day}')")
    await p.wait_for_function("document.querySelector('#person-next').disabled")
    assert await p.input_value("#person-date") > day and await p.is_disabled("#person-today")


async def test_arrow_keys_ignored_while_typing(trips_page, trips_server, pid):
    day = await open_person(trips_page, trips_server, pid)
    await trips_page.focus("#person-date")
    await trips_page.keyboard.press("ArrowLeft")
    await trips_page.wait_for_timeout(300)
    assert day in await trips_page.evaluate("location.hash")


async def test_summary_line_focuses_map_and_story(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    await p.get_by_role("button", name="8:10 AM arrived at School").click()
    assert await p.locator(".person-line-btn[aria-current=true]").count() == 1
    assert await p.locator(".story-item.is-picked").count() == 1
    assert await p.locator("#map path[stroke-dasharray='4 4']").count() >= 1, (
        "a highlight ring on the map"
    )
    title = await p.locator(".story-item.is-picked .story-title").inner_text()
    assert title == "School"
    assert p.fp_errors == [], "focusing a line must not throw"


async def test_wrong_sightings_sentence_has_a_show_button(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    note = p.locator(".person-suspect-note")
    assert "1 sighting looked wrong and was left out." in await note.inner_text()
    await p.uncheck("#person-suspect")
    await note.get_by_role("button", name="Show").click()
    assert await p.is_checked("#person-suspect"), "Show switches the faint sightings back on"


async def test_every_summary_line_can_be_pressed_without_an_error(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    for button in await p.locator(".person-line-btn").all():
        await button.click()
    await p.locator(".story-item").first.click()
    assert p.fp_errors == []


async def test_story_row_selects_and_hash_is_a_route(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    await p.locator(".story-item").first.focus()
    await p.keyboard.press("ArrowDown")
    await p.keyboard.press("Enter")
    assert await p.locator(".story-item.is-picked").count() == 1
    assert await p.locator(".strip-bar rect.is-picked").count() == 1
    assert p.fp_errors == []


async def test_person_view_hides_dashboard_filters_and_leaving_restores(
    trips_page, trips_server, pid
):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    assert not await p.locator("section.controls").is_visible()
    await p.click("#person-back")
    await p.wait_for_selector("#tab-dashboard", state="visible")
    assert await p.locator("section.controls").is_visible()
    assert await p.locator("#tab-person").is_hidden()
    assert await p.locator(".fp-tabs .fp-tab.active").get_attribute("data-tab") == "dashboard"


async def test_phone_width_has_no_sideways_scroll(trips_page, trips_server, pid):
    await trips_page.set_viewport_size({"width": 375, "height": 800})
    await open_person(trips_page, trips_server, pid)
    over = await trips_page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert over <= 0


async def test_phone_opens_at_the_page_and_a_focus_brings_the_map_back(
    trips_page, trips_server, pid
):
    await trips_page.set_viewport_size({"width": 375, "height": 800})
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    top = "document.getElementById('person-page').getBoundingClientRect().top"
    await p.wait_for_function(f"{top} < 200")
    await p.get_by_role("button", name="8:10 AM arrived at School").click()
    await p.wait_for_function(
        "document.querySelector('.map-pane').getBoundingClientRect().top > -50"
    )


async def test_reduced_motion_has_no_animation_on_the_page(browser_session, trips_server, pid):
    browser, _ = browser_session
    ctx = await browser.new_context(bypass_csp=True, timezone_id="UTC", reduced_motion="reduce")
    await stub_osm_tiles(ctx)
    page = await ctx.new_page()
    try:
        await open_person(page, trips_server, pid)
        names = await page.evaluate(
            "[...document.querySelectorAll('.person *')]"
            ".map(e => getComputedStyle(e).animationName).filter(n => n !== 'none')"
        )
        assert names == [], "nothing on the page animates under reduced motion"
    finally:
        await ctx.close()

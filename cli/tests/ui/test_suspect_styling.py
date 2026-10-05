"""A sighting that looks wrong is drawn faintly with its reason, can be hidden, and adds no distance."""

# ruff: noqa: E501

from __future__ import annotations

import pytest

from ._person_helpers import ensure_person, open_person
from ._trips_helpers import focus_sightings, open_day

pytestmark = pytest.mark.asyncio(loop_scope="session")
REASON = "looks wrong"


async def test_raw_view_marks_the_row_and_the_marker(trips_page, trips_server):
    await open_day(trips_page, trips_server, "gap", prefs={"findplus.dayView": "raw"})
    p = trips_page
    await p.wait_for_selector(".tl-item")
    row = p.locator(".tl-item.is-suspect")
    assert await row.count() == 1
    assert REASON in await row.locator(".tl-suspect").inner_text()
    assert await p.locator(".marker-num--suspect").count() == 1
    assert REASON in (
        await p.locator(".marker-num--suspect").first.evaluate("e => e.parentElement.title")
    )


async def test_toggle_hides_and_restores_and_is_remembered(trips_page, trips_server):
    await open_day(trips_page, trips_server, "gap", prefs={"findplus.dayView": "raw"})
    p = trips_page
    await p.wait_for_selector("#suspect-group:not([hidden])")
    assert await p.is_checked("#toggle-suspect"), "on by default"
    await p.uncheck("#toggle-suspect")
    assert await p.locator(".tl-item.is-suspect").count() == 0
    assert await p.locator(".marker-num--suspect").count() == 0
    await p.reload()
    await p.wait_for_selector("#app-shell[data-fp-ready]")
    await p.evaluate(
        f"import('/static/app/timeline.js').then(m => m.loadDay('{trips_server['days']['gap']}'))"
    )
    await focus_sightings(p)
    await p.wait_for_selector(".tl-item")
    assert not await p.is_checked("#toggle-suspect"), "remembered in this browser"
    await p.check("#toggle-suspect")
    assert await p.locator(".tl-item.is-suspect").count() == 1


async def test_toggle_is_absent_on_a_day_with_nothing_suspect(trips_page, trips_server):
    await open_day(trips_page, trips_server, "school", prefs={"findplus.dayView": "raw"})
    await trips_page.wait_for_selector(".tl-item")
    assert await trips_page.locator("#suspect-group").is_hidden()


async def test_day_story_draws_a_faint_dot_in_a_dashed_ring(trips_page, trips_server):
    await open_day(trips_page, trips_server, "gap", prefs={"findplus.dayView": "story"})
    p = trips_page
    await p.wait_for_selector(".story-item")
    assert await p.locator("#map path[stroke-dasharray='3 3']").count() == 1
    await p.locator("#map path[stroke-dasharray='3 3']").first.dispatch_event("mouseover")
    await p.locator(".leaflet-tooltip", has_text=REASON).wait_for()
    await p.uncheck("#toggle-suspect")
    assert await p.locator("#map path[stroke-dasharray='3 3']").count() == 0


async def test_distance_leaves_the_suspect_sighting_out(trips_page, trips_server):
    await open_day(trips_page, trips_server, "gap", prefs={"findplus.dayView": "raw"})
    await trips_page.wait_for_selector(".stats")
    text = await trips_page.locator(".stat", has_text="Distance").first.inner_text()
    miles = float(text.split()[0])
    assert miles < 50, f"a 45,-70 jump must not count as {miles} miles"


async def test_person_map_rings_the_suspect_and_the_toggle_hides_it(trips_page, trips_server):
    pid = ensure_person(trips_server)
    await open_person(trips_page, trips_server, pid, day_key="gap")
    p = trips_page
    assert await p.locator("#map path[stroke-dasharray='3 3']").count() >= 1
    await p.uncheck("#person-suspect")
    assert await p.locator("#map path[stroke-dasharray='3 3']").count() == 0
    await p.check("#person-suspect")
    assert await p.locator("#map path[stroke-dasharray='3 3']").count() >= 1

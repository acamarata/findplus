"""Tracker focus (dashboard 1.3): one tracker in the side panel and on the map.

Purpose    : Focus from a Latest row, from the `findplus:focus-tracker` event (the map
             popup and the Activity lines), and from `#/tracker/<id>`; the Story |
             Sightings switch over the existing day body; Back restoring the tab, the
             filter and the map.
Inputs     : The day-story fixture server (trackers TAG-SON "Sam" and TAG-MOM "Mia").
Outputs    : Assertions only.
Constraints: Headless Chromium. The seeded "school" day is yesterday, so tests load
             it through timeline.loadDay.
"""

# ruff: noqa: E501  (inline JS snippets)
from __future__ import annotations

import httpx
import pytest

from ._latest_helpers import active_tab, boot, dispatch_focus, ensure_alex, focus_state

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(autouse=True)
def _alex(trips_server):
    ensure_alex(trips_server)


async def _load_day(page, day):
    await page.evaluate("d => import('/static/app/timeline.js').then((m) => m.loadDay(d))", day)


async def test_a_tracker_row_focuses_it(trips_page, trips_server):
    p = trips_page
    await boot(p, trips_server)
    await p.click("#fp-latest-list .fp-latest-row--tracker .fp-latest-main")
    await p.wait_for_selector("#fp-latest-focus:not([hidden])")
    assert await p.is_hidden("#fp-latest-list")
    assert (await p.inner_text("#fp-focus-name")) == "Mia"
    assert await p.is_visible("#fp-focus-back")
    assert await p.locator("#fp-latest-focus [data-act=edit]").count() == 1
    await p.wait_for_function(
        "() => import('/static/app/state.js').then((m) => m.state.deviceFilter === 'TAG-MOM')"
    )
    st = await focus_state(p)
    assert st["hash"] == "#/tracker/TAG-MOM"
    assert st["tracks"] in ([], ["TAG-MOM"]), "the map shows only that tracker"


async def test_the_event_focuses_and_switches_to_latest(trips_page, trips_server):
    p = trips_page
    await boot(p, trips_server)
    await p.click('.fp-tabs [data-tab="places"]')
    await dispatch_focus(p, "TAG-SON")
    await p.wait_for_selector("#fp-latest-focus:not([hidden])")
    assert await active_tab(p) == "latest"
    assert await p.inner_text("#fp-focus-name") == "Sam"
    await p.wait_for_function(
        "() => import('/static/app/state.js').then((m) => m.state.timeline && m.state.timeline.tracks.every((t) => t.device_id === 'TAG-SON'))"
    )


async def test_back_restores_the_previous_tab_filter_and_map(trips_page, trips_server):
    p = trips_page
    await boot(p, trips_server)
    await p.click('.fp-tabs [data-tab="activity"]')
    await dispatch_focus(p, "TAG-MOM")
    await p.wait_for_selector("#fp-latest-focus:not([hidden])")
    await p.click("#fp-focus-back")
    await p.wait_for_selector("#tab-activity:not([hidden])")
    assert await active_tab(p) == "activity"
    assert await p.is_hidden("#fp-latest-focus")
    await p.wait_for_function(
        "() => import('/static/app/state.js').then((m) => m.state.deviceFilter === '' && m.state.timeline && m.state.timeline.tracks.length === 2)"
    )
    assert await p.input_value("#device-filter") == ""
    assert not (await focus_state(p))["hash"].startswith("#/tracker")


async def test_back_from_a_latest_row_shows_the_list_again(trips_page, trips_server):
    p = trips_page
    await boot(p, trips_server)
    await p.click("#fp-latest-list .fp-latest-row--tracker .fp-latest-main")
    await p.wait_for_selector("#fp-latest-focus:not([hidden])")
    await p.click("#fp-focus-back")
    await p.wait_for_selector("#fp-latest-list .fp-latest-row")
    assert await p.is_visible("#fp-latest-list")
    assert await active_tab(p) == "latest"


async def test_the_hash_route_focuses_on_load(trips_page, trips_server):
    p = trips_page
    await boot(p, trips_server, "/#/tracker/TAG-SON")
    await p.wait_for_selector("#fp-latest-focus:not([hidden])")
    assert await p.inner_text("#fp-focus-name") == "Sam"
    assert await active_tab(p) == "latest"
    await p.evaluate("window.location.hash = '#/tracker/TAG-MOM'")
    await p.wait_for_function("document.getElementById('fp-focus-name').textContent === 'Mia'")


async def test_story_and_sightings_switch(trips_page, trips_server):
    p = trips_page
    await boot(p, trips_server)
    await dispatch_focus(p, "TAG-SON")
    await p.wait_for_selector("#fp-latest-focus:not([hidden])")
    await _load_day(p, trips_server["days"]["school"])
    await p.wait_for_selector("#story .story-item")
    story = p.locator('#fp-latest-focus [data-view="story"]')
    sightings = p.locator('#fp-latest-focus [data-view="raw"]')
    assert await story.get_attribute("aria-pressed") == "true"
    await sightings.click()
    await p.wait_for_selector("#tracks .tl-item")
    assert await sightings.get_attribute("aria-pressed") == "true"
    assert await p.is_hidden("#story")
    await story.click()
    await p.wait_for_selector("#story .story-item")
    assert await p.is_hidden("#tracks .tl-item")
    assert await p.is_hidden("#view-switch"), "the old switch is replaced by Story | Sightings"


async def test_a_sighting_is_selected_when_the_event_names_one(trips_page, trips_server):
    p = trips_page
    await boot(p, trips_server)
    day = trips_server["days"]["school"]
    body = httpx.get(
        f"{trips_server['base']}/api/timeline", params={"day": day, "device_id": "TAG-SON"}
    ).json()
    point = body["tracks"][0]["points"][3]["id"]
    await _load_day(p, day)
    await dispatch_focus(p, "TAG-SON", point)
    await p.wait_for_selector(f'#tracks .tl-item[data-id="{point}"]')
    await p.wait_for_function(
        f"() => import('/static/app/state.js').then((m) => m.state.selectedId === {point})"
    )
    assert (
        await p.locator('#fp-latest-focus [data-view="raw"]').get_attribute("aria-pressed")
        == "true"
    )


async def test_leaving_latest_by_another_tab_ends_the_focus(trips_page, trips_server):
    p = trips_page
    await boot(p, trips_server)
    await dispatch_focus(p, "TAG-MOM")
    await p.wait_for_selector("#fp-latest-focus:not([hidden])")
    await p.click('.fp-tabs [data-tab="places"]')
    await p.wait_for_function(
        "() => import('/static/app/state.js').then((m) => m.state.deviceFilter === '')"
    )
    assert not (await focus_state(p))["hash"].startswith("#/tracker")
    await p.click('.fp-tabs [data-tab="latest"]')
    await p.wait_for_selector("#fp-latest-list .fp-latest-row")
    assert await p.is_hidden("#fp-latest-focus")

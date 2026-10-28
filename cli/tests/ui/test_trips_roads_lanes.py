"""Draw likely roads (absent / present routing server), family lanes, lock purge, axe."""

from __future__ import annotations

import json
import re

import pytest
from axe_playwright_python.async_playwright import Axe

from ._trips_helpers import open_day, show_legacy_story, start_fake_osrm

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _set_endpoint(page, base, value):
    resp = await page.request.post(
        base + "/api/settings/routing.endpoint",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()


async def test_roads_toggle_disabled_without_a_server(trips_page, trips_server):
    requests = []
    trips_page.on("request", lambda r: requests.append(r.url) if "/trips/route" in r.url else None)
    await _set_endpoint(trips_page, trips_server["base"], "")
    await open_day(trips_page, trips_server, "school")
    await trips_page.wait_for_selector(".story-item")
    assert await trips_page.locator("#toggle-roads").is_disabled()
    note = await trips_page.locator("#roads-note").inner_text()
    assert "sent to that server" in note and "no routing server is set" in note
    assert await trips_page.locator("#roads-note a").get_attribute("href") == "#settings"
    assert requests == []


async def test_roads_present_draws_solid_routes_with_the_label(trips_page, trips_server):
    url, hits, stop = start_fake_osrm()
    try:
        await _set_endpoint(trips_page, trips_server["base"], url)
        await open_day(trips_page, trips_server, "school")
        await trips_page.wait_for_selector(".story-item")
        box = trips_page.locator("#toggle-roads")
        await trips_page.wait_for_function("!document.getElementById('toggle-roads').disabled")
        assert hits == [], "nothing is sent until the box is ticked"
        await box.check()
        await trips_page.wait_for_function(
            "document.querySelectorAll('#map path[stroke-dasharray]').length === 0"
        )
        assert len(hits) >= 2
        note = trips_page.locator("#route-note")
        assert (
            "Likely route between sparse sightings, not a record of the road driven"
            in await note.inner_text()
        )
        await box.uncheck()
        await trips_page.wait_for_function(
            "document.querySelectorAll('#map path[stroke-dasharray]').length === 2"
        )
        assert await note.count() == 0
    finally:
        await _set_endpoint(trips_page, trips_server["base"], "")
        stop()


async def test_group_shows_family_lanes(trips_page, trips_server):
    await open_day(trips_page, trips_server, "school", device="")
    await trips_page.wait_for_selector(
        "#fp-group-select option[value]:nth-child(2)", state="attached"
    )
    await trips_page.select_option("#fp-group-select", label="Family")
    await show_legacy_story(trips_page)
    await trips_page.wait_for_selector(".lane .strip-bar")
    assert await trips_page.locator(".lane").count() == 2
    assert await trips_page.locator(".lane-legend").count() == 1
    # A tracker that belongs to a person is named for the person (O13): "Sam (bag)".
    await trips_page.locator(".lane-name", has_text=re.compile("Mia|bag")).click()
    await trips_page.get_by_role("heading", name="Day story for Mia").wait_for()


async def test_lock_purge_leaves_nothing(trips_page, trips_server):
    await open_day(trips_page, trips_server, "school")
    await trips_page.wait_for_selector(".story-item")
    await trips_page.evaluate("import('/static/app/lock.js').then(m => m.purgeRenderedData())")
    html = await trips_page.content()
    for leaked in ("Trip to School", "Day story for Sam", "story-label", "7:42 AM"):
        assert leaked not in html, f"{leaked!r} survived the purge"
    assert await trips_page.locator("#story").is_hidden()
    assert await trips_page.locator("#map path.leaflet-interactive").count() == 0


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 375])
async def test_story_is_axe_clean(trips_page, trips_server, theme, width):
    await trips_page.set_viewport_size({"width": width, "height": 900})
    await open_day(trips_page, trips_server, "school")
    await trips_page.wait_for_selector(".story-item")
    await trips_page.evaluate("(t) => { document.documentElement.dataset.theme = t; }", theme)
    opts = {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]}}
    res = await Axe().run(trips_page, context="#timeline-pane", options=opts)
    bad = [v for v in res.response["violations"] if v["impact"] in ("serious", "critical")]
    assert not bad, [(v["id"], [n["target"] for n in v["nodes"]]) for v in bad]

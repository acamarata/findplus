"""The dashboard redraws by itself, and its empty map and pane say why they are empty.

Purpose    : (2) After an unlock or the first successful poll the page used to
             stay on its old banner, empty tiles and empty map until a manual
             reload. live_refresh.js now notices the status change and reloads
             the banner, tiles, device list, timeline and map.
             (4) With nothing to draw, the map carries a one-line note, fits the
             whole world to its own box, and the right pane differs for locked,
             no data yet, and a quiet day.
             (5) Axe finds nothing serious on the new banner and empty states.
Constraints: Status is stubbed; timeline/devices are the real seeded server, so
             "it refreshed" is proven by the requests the page makes. The
             Playwright clock moves the page's timers on instead of waiting.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from axe_playwright_python.async_playwright import Axe

from ._live_helpers import feed_for, open_dashboard, reload_status, show_day, stub_google_locked
from .conftest import set_theme

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _activity_body(page):
    """The all-trackers day body lives in the Activity tab now (dashboard 1.3)."""
    await page.add_init_script("localStorage.setItem('findplus.panelTab','activity')")


LOCKED = {t: ("needs_shared_key", 0) for t in ("TAG-HOME", "TAG-AWAY", "TAG-STALE")}
GOOD = {t: ("ok", 1) for t in ("TAG-HOME", "TAG-AWAY", "TAG-STALE")}
QUIET_DAY = "2000-01-01"
NOTE = "#map-empty"


async def test_the_page_redraws_by_itself_when_the_poll_changes(page, base_url):
    await page.clock.install()
    await stub_google_locked(page)
    feed = await feed_for(page, base_url)
    feed.cycle(LOCKED, 300, observations_today=0)
    seen: list[str] = []
    page.on("request", lambda r: seen.append(r.url.split("?")[0].rsplit("/api/", 1)[-1]))
    await open_dashboard(page, base_url)
    await page.locator("#alert .alert-action").wait_for(state="visible")
    before = {name: seen.count(name) for name in ("timeline", "devices")}

    # The unlock finished and the poll that followed worked. No reload, no click.
    feed.cycle(GOOD, 310, observations_today=7, observations_total=9)
    await page.clock.run_for(11000)
    await page.wait_for_function(
        "() => document.getElementById('card-today').textContent === '7'", timeout=15000
    )
    assert await page.locator("#alert.hidden").count() == 1  # the locked banner is gone
    # The status redraws first; the lists follow a beat later.
    for _ in range(100):
        if all(seen.count(name) > before[name] for name in before):
            break
        await page.wait_for_timeout(100)
    assert seen.count("timeline") > before["timeline"], "the map and timeline were not re-read"
    assert seen.count("devices") > before["devices"], "the device list was not re-read"


async def test_a_quiet_status_does_not_reload_the_timeline_in_fast_mode(page, base_url):
    """While waiting for a poll the status is read often; the timeline only
    when the status actually changed."""
    await page.clock.install()
    await stub_google_locked(page)
    feed = await feed_for(page, base_url)
    feed.cycle(LOCKED, 320)
    seen: list[str] = []
    page.on("request", lambda r: seen.append(r.url.split("?")[0].rsplit("/api/", 1)[-1]))
    await open_dashboard(page, base_url)
    await page.locator("#alert .alert-action").wait_for(state="visible")
    timelines, hits = seen.count("timeline"), feed.hits
    await page.clock.run_for(31000)  # three attention-cadence ticks, nothing new
    await page.wait_for_timeout(300)
    assert feed.hits > hits, "the status was not watched"
    assert seen.count("timeline") == timelines


async def test_the_map_is_bare_so_it_says_why_and_the_pane_agrees_when_locked(page, base_url):
    await stub_google_locked(page)
    feed = await feed_for(page, base_url)
    feed.cycle(LOCKED, 330)
    await open_dashboard(page, base_url)
    await show_day(page, QUIET_DAY)
    pane = page.locator("#tracks [data-empty-day='locked']")
    await pane.wait_for(state="visible")
    assert "Locations are locked" in await pane.inner_text()
    assert await page.inner_text(NOTE) == "Locations are locked"
    await pane.get_by_role("button", name="Unlock locations").click()
    await page.locator("#fp-auth-google-unlock").wait_for(state="visible", timeout=10000)


async def test_no_data_yet_reads_differently_from_a_quiet_day(page, base_url):
    feed = await feed_for(page, base_url)
    feed.cycle(GOOD, 340, observations_today=0, observations_total=0)
    await open_dashboard(page, base_url)
    await show_day(page, QUIET_DAY)
    pane = page.locator("#tracks [data-empty-day='nodata']")
    await pane.wait_for(state="visible")
    text = await pane.inner_text()
    assert "No locations yet" in text and "updates by itself" in text
    assert await pane.get_by_role("button").count() == 0
    assert await page.inner_text(NOTE) == "No locations to show yet"

    # Data exists for other days: the same empty day is now just quiet.
    feed.cycle(GOOD, 350, observations_today=2, observations_total=9)
    await reload_status(page)
    quiet = page.locator("#tracks [data-empty-day='quiet']")
    await quiet.wait_for(state="visible")
    assert "No observations recorded for this day." in await quiet.inner_text()
    assert await page.inner_text(NOTE) == "No locations on this day"
    await quiet.get_by_role("button", name="Show latest location").click()
    await page.wait_for_function(
        "(d) => document.getElementById('day-picker').value !== d", arg=QUIET_DAY, timeout=10000
    )


async def test_the_pane_follows_a_status_change_without_a_reload(page, base_url):
    feed = await feed_for(page, base_url)
    feed.cycle(GOOD, 360, observations_today=0, observations_total=0)
    await open_dashboard(page, base_url)
    await show_day(page, QUIET_DAY)
    await page.locator("#tracks [data-empty-day='nodata']").wait_for(state="visible")
    feed.cycle(LOCKED, 370, observations_today=0, observations_total=0)
    await reload_status(page)
    await page.locator("#tracks [data-empty-day='locked']").wait_for(state="visible")
    assert await page.locator("#tracks > *").count() == 1


async def test_a_map_with_points_has_no_note(page, base_url):
    await open_dashboard(page, base_url)
    await page.wait_for_selector(".marker-num", timeout=15000)
    assert await page.locator(NOTE).count() == 0 or await page.locator(NOTE).is_hidden()


async def test_an_empty_map_fits_the_whole_world_into_its_box(page, base_url):
    async def no_devices(route):
        await route.fulfill(json={"devices": []})

    async def no_places(route):
        await route.fulfill(json=[])

    async def no_tracks(route):
        await route.fulfill(json={"tracks": []})

    # Before navigation, so the boot sees an install with nothing to fit to.
    await page.route("**/api/devices", no_devices)
    await page.route("**/api/places", no_places)
    await page.route("**/api/timeline*", no_tracks)
    await open_dashboard(page, base_url)
    inside = await page.evaluate(
        """async () => {
            const { state } = await import('/static/app/state.js');
            const world = L.latLngBounds([[-58, -170], [78, 175]]);
            const b = state.map.getBounds();
            return [b.contains(world), b.toBBoxString(), state.map.getZoom()];
        }"""
    )
    assert inside[0], inside


@pytest.mark.parametrize("theme", ("dark", "light"))
async def test_no_serious_axe_violations_on_the_new_states(page, base_url, theme):
    feed = await feed_for(page, base_url)
    silent = {t: ("no_location", 0) for t in LOCKED}
    feed.cycle(silent, 380, observations_today=0, observations_total=0)
    await open_dashboard(page, base_url)
    await show_day(page, QUIET_DAY)
    await page.locator("#alert.info").wait_for(state="visible")
    await page.locator("#tracks [data-empty-day]").wait_for(state="visible")
    await set_theme(page, theme)
    options = {
        "resultTypes": ["violations"],
        "runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]},
    }
    found = (await Axe().run(page, options=options)).response["violations"]
    bad = [v for v in found if v.get("impact") in ("serious", "critical")]
    assert not bad, [(v["id"], [n.get("target") for n in v["nodes"][:3]]) for v in bad]

"""Playwright tests for the Places side panel, presence chips and default view.

Seed data (cli/tests/ui/conftest.py): devices TAG-HOME/TAG-AWAY/TAG-STALE;
place "Home" at (41.1, -80.1) r=200m with TAG-HOME and TAG-AWAY both inside
it. Split out of test_places.py (T1, 2026-09-22, PRI rule-7 300-line file
cap); the dialog + map-circle tests stay there.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

HOME_LAT, HOME_LON = 41.100000, -80.100000


async def _open_dashboard(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")


async def _wait_for_map_settled(page):
    """bootDashboard()'s own fitBounds calls (setDefaultView(), then
    renderMap() after loadDay()) run an animated Leaflet zoom transition.
    _stop() does not cancel that transition's completion timeout, so a
    setView() made while `_animatingZoom` is still true is silently
    overwritten later when that timeout fires and resets the view straight
    back to boot's own target -- CI run 36140185227's real cause: the map
    "barely moved" (1e-6 degrees) because both our forced setView and the
    row click's setView landed mid-transition and were reverted. Poll from
    the Python side (not page.wait_for_function -- its tighter poll loop
    resolves right at the flip and still raced the same revert) until the
    flag is down.
    """
    for _ in range(40):
        animating = await page.evaluate(
            "async () => { const { state } = await import('/static/app/state.js'); "
            "return !!(state.map && state.map._animatingZoom); }"
        )
        if not animating:
            return
        await page.wait_for_timeout(50)
    raise AssertionError("map never stopped animating")


async def test_presence_chip_appears(page, base_url):
    await _open_dashboard(page, base_url)
    await page.click("#btn-devices")
    await page.wait_for_selector('[data-device-id="TAG-HOME"]')
    chip = page.locator('[data-device-id="TAG-HOME"] .fp-presence-chip')
    await chip.wait_for(state="visible")
    assert "Home" in await chip.inner_text()


async def test_default_view_fits_the_tracked_devices_latest_fixes(page, base_url):
    """U4: the map used to open on a hardcoded US-centre view (Kansas) no
    matter what the account actually tracks. Calling setDefaultView()
    directly (rather than only trusting whatever the day's own fitBounds
    happens to do) pins the fix at its source."""
    await _open_dashboard(page, base_url)
    center = await page.evaluate(
        """async () => {
            const { setDefaultView } = await import('/static/app/map.js');
            const { state } = await import('/static/app/state.js');
            await setDefaultView();
            const c = state.map.getCenter();
            return { lat: c.lat, lng: c.lng };
        }"""
    )
    # The seeded devices/places sit near HOME_LAT/HOME_LON; the old default
    # was 39.5, -98.35 (Kansas) regardless of any seeded data.
    assert abs(center["lat"] - HOME_LAT) < 2
    assert abs(center["lng"] - HOME_LON) < 2


async def test_places_list_renders_the_seeded_place(page, base_url):
    """U5: the side panel used to show only 'Add place' and the hint, even
    with places saved -- an off-screen place could not be found, edited or
    deleted at all."""
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    row = page.locator("#fp-places-list [data-place-id]", has_text="Home")
    await row.wait_for(state="visible")
    text = await row.inner_text()
    assert "Home" in text
    assert "200" in text  # the seeded "Home" place's radius, in the metres meta


async def test_places_list_edit_opens_the_dialog_prefilled(page, base_url):
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    row = page.locator("#fp-places-list [data-place-id]", has_text="Home")
    await row.wait_for(state="visible")
    await row.get_by_text("Edit", exact=True).click()
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")
    assert await dialog.locator("#fp-place-name").input_value() == "Home"


async def test_places_list_centre_click_pans_the_map(page, base_url):
    """Clicking the row body (not a button) centres the map on that place —
    U5's click-to-centre. The seeded default view is a world/local view far
    from a 0-zoom accident, so a real pan is distinguishable from a no-op."""
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    row = page.locator("#fp-places-list [data-place-id]", has_text="Home")
    await row.wait_for(state="visible")
    # bootDashboard() fits the map to the seeded data on its own (setDefaultView(),
    # then renderMap()'s own fitBounds() after loadDay()) -- both run async and are
    # not awaited by anything the places list depends on, so the row above can be
    # visible and clickable well before that chain lands. data-fp-ready waits for
    # the chain itself; _wait_for_map_settled() waits for its animation too (see
    # its docstring -- CI run 36140185227's real cause).
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")
    await _wait_for_map_settled(page)
    before = await page.evaluate(
        "async () => { const { state } = await import('/static/app/state.js'); "
        "state.map.setView([0, 0], 2, { animate: false }); return state.map.getCenter(); }"
    )
    await row.click(position={"x": 5, "y": 5})  # the swatch corner, never a button
    # centerOnPlace() (places.js) animates too; read the center only once it lands.
    await _wait_for_map_settled(page)
    after = await page.evaluate(
        "async () => { const { state } = await import('/static/app/state.js'); "
        "return state.map.getCenter(); }"
    )
    assert abs(after["lat"] - before["lat"]) > 1 or abs(after["lng"] - before["lng"]) > 1


async def test_places_list_delete_removes_the_row(page, base_url):
    resp = await page.request.post(
        base_url + "/api/places",
        data=json.dumps(
            {
                "name": "List Delete Me",
                "latitude": HOME_LAT,
                "longitude": HOME_LON + 0.01,
                "radius_meters": 60,
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()

    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    row = page.locator("#fp-places-list [data-place-id]", has_text="List Delete Me")
    await row.wait_for(state="visible")
    page.once("dialog", lambda d: d.accept())
    await row.get_by_text("Delete", exact=True).click()
    await row.wait_for(state="detached")

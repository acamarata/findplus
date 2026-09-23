"""Browser tests for the wizard's Places step (E13 UAT2 N6).

Split out of test_setup_wizard_notifications.py (T1, 2026-09-22, PRI rule-7
size cap): that file was at its 300-line cap once U17's own new coverage
landed, and this step's default-view/list-refresh coverage is unrelated to
that file's Notifications/Sign-in focus.

Seed data (cli/tests/ui/_seed_script.py): TAG-HOME/TAG-AWAY tracked with real
fixes near HOME_LAT/HOME_LON; place "Home" at the same point.
"""

from __future__ import annotations

import json

import pytest

from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")

HOME_LAT, HOME_LON = 41.100000, -80.100000


async def _set_completed_at(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _set_last_step(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.last_step",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _open_step(page, base_url, step):
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, step)
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)


async def test_places_step_opens_the_map_fitted_to_tracked_devices(page, base_url):
    """UAT N6: the wizard's borrowed map opened at world zoom with no
    tracker markers to give it a reason to zoom in. onEnter now calls the
    same setDefaultView() the dashboard uses: tracked devices' latest
    fixes, else saved places, never the plain [20, 0] world view."""
    try:
        await _open_step(page, base_url, "places")
        await page.wait_for_selector("#fp-setup-map-host #map", timeout=15000)
        center = await page.evaluate(
            """async () => {
                const { state } = await import('/static/app/state.js');
                const c = state.map.getCenter();
                return { lat: c.lat, lng: c.lng };
            }"""
        )
        assert abs(center["lat"] - HOME_LAT) < 2
        assert abs(center["lng"] - HOME_LON) < 2
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_places_step_draws_tracked_device_markers_on_a_true_first_run(page, base_url):
    """UAT4 N36: a true first run never calls bootDashboard() (main.js
    redirects to the wizard before that runs), so state.timeline stays null
    and the borrowed map used to show only the seeded place circles, with no
    way to see where the trackers actually are to draw a geofence around
    them. map.js's renderTrackedDeviceMarkers() draws one marker per tracked
    device's latest fix whenever there is no timeline loaded yet -- the seed
    (TAG-HOME, TAG-AWAY) gives two."""
    try:
        await _open_step(page, base_url, "places")
        await page.wait_for_selector("#fp-setup-map-host #map", timeout=15000)
        await page.wait_for_function(
            "() => document.querySelectorAll('#map .leaflet-marker-icon').length > 0",
            timeout=15000,
        )
        marker_count = await page.locator("#map .leaflet-marker-icon").count()
        assert marker_count == 2
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_places_step_add_button_has_a_gap_above_the_map(page, base_url):
    """N49: "Add a place" sat flush on the borrowed map's top border --
    fp-setup-places-add (components.css) now gives it a real gap."""
    try:
        await _open_step(page, base_url, "places")
        await page.wait_for_selector("#fp-setup-map-host #map", timeout=15000)
        add_box = await page.get_by_role("button", name="Add a place").bounding_box()
        map_box = await page.locator("#fp-setup-map-host #map").bounding_box()
        gap = map_box["y"] - (add_box["y"] + add_box["height"])
        assert gap > 0, gap
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_places_step_list_refreshes_after_adding_a_place(page, base_url):
    """UAT N6: a place added through the wizard's own dialog saved fine (it
    is the dashboard's shared places_dialog.js) but never appeared in this
    step's own list -- the dialog's onSaved callback reloads the dashboard's
    list, which sits hidden behind the wizard, not this one."""
    try:
        await _open_step(page, base_url, "places")
        await page.wait_for_selector("#fp-setup-map-host #map", timeout=15000)
        assert "Grandma" not in await page.locator("#fp-setup-places-list").inner_text()

        await page.get_by_role("button", name="Add a place").click()
        dialog = page.locator("#fp-place-dialog")
        await dialog.wait_for(state="visible")
        await dialog.locator("#fp-place-name").fill("Grandma")
        await dialog.get_by_text("Save", exact=True).click()
        await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")

        await page.wait_for_function(
            "() => document.getElementById('fp-setup-places-list').textContent.includes('Grandma')",
            timeout=15000,
        )
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)

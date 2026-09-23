"""UAT2 N5/N8: the place dialog's "Use a tracker's last location" picker and
its opt-in address search.

Seed (cli/tests/ui/conftest.py): TAG-HOME ("Ali's Keys"), TAG-AWAY and
TAG-STALE are tracked; TAG-AIR is not. Split out of test_places.py (already
at the size cap) rather than appended there.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

HOME_LAT, HOME_LON = 41.100000, -80.100000


async def _open_add_place_dialog(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")
    await page.click('button[data-tab="places"]')
    await page.click("#fp-add-place-btn")
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")
    return dialog


async def test_tracker_select_lists_each_tracker_once_on_first_open(page, base_url):
    """N5: `refreshTrackers()` used to run once from the locator's factory and
    again from the dialog's own open handler, and the two overlapping fetches
    each cleared-then-appended into the same <select> -- every tracker (and
    the placeholder) listed twice the very first time the dialog opened."""
    dialog = await _open_add_place_dialog(page, base_url)
    select = dialog.locator("#fp-place-tracker-select")
    await page.wait_for_function(
        "() => document.getElementById('fp-place-tracker-select').options.length > 1"
    )
    labels = await select.locator("option").evaluate_all("els => els.map((e) => e.textContent)")
    # Placeholder + TAG-HOME/TAG-AWAY/TAG-STALE (tracked); TAG-AIR is not tracked.
    assert len(labels) == 4, labels
    assert len(labels) == len(set(labels)), labels
    assert "Ali's Keys" in labels


async def test_use_tracker_location_sets_a_status_line(page, base_url):
    """N8: picking "Use" moved the hidden lat/lon fields with no visible sign
    that anything had happened."""
    dialog = await _open_add_place_dialog(page, base_url)
    await dialog.locator("#fp-place-tracker-select").select_option(label="Ali's Keys")
    await dialog.locator("#fp-place-use-tracker-btn").click()
    status = dialog.locator("#fp-place-locator-status")
    # "Loading…" is the transient status the click sets first -- wait past it
    # for the real one useTrackerLocation() writes once /api/latest resolves.
    await page.wait_for_function(
        "() => document.getElementById('fp-place-locator-status')"
        ".textContent.startsWith('Location')"
    )
    assert await status.inner_text() == "Location set from Ali's Keys."


async def test_search_result_pick_sets_a_status_line(page, base_url):
    """N8: the same missing feedback for the address-search half."""
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")
    await page.click('button[data-tab="places"]')

    async def handle(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                [
                    {
                        "display_name": "1600 Amphitheatre Pkwy",
                        "latitude": 37.42,
                        "longitude": -122.08,
                    }
                ]
            ),
        )

    await page.route("**/api/places/search*", handle)

    dialog = await _open_add_place_dialog(page, base_url)
    await dialog.locator("#fp-place-search-input").fill("1600 Amphitheatre Pkwy")
    await dialog.locator("#fp-place-search-btn").click()
    await dialog.locator("#fp-place-search-results").wait_for(state="visible")
    await dialog.get_by_text("1600 Amphitheatre Pkwy", exact=True).click()

    status = dialog.locator("#fp-place-locator-status")
    await page.wait_for_function(
        "() => document.getElementById('fp-place-locator-status')"
        ".textContent.includes('Amphitheatre')"
    )
    assert await status.inner_text() == "Location set from 1600 Amphitheatre Pkwy."

"""Browser tests for the place dialog's "Pick on map" control (UAT6 N13).

Seed data (cli/tests/ui/conftest.py): same throwaway install as
test_places.py, map centred near (41.1, -80.1).

Pick-on-map closes the modal <dialog> (its backdrop otherwise blocks every
click on the page under it, so the map underneath could never be clicked
while the dialog stayed open) and draws a draggable marker plus a radius
circle directly on the shared map; a click there, a drag, or the arrow keys
reposition it before "Set location" reopens the dialog with the new point.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_add_dialog(page, base_url):
    await page.goto(base_url + "/")
    await page.click('button[data-tab="places"]')
    await page.click("#fp-add-place-btn")
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")
    return dialog


async def test_pick_on_map_closes_the_dialog_and_draws_a_marker(page, base_url):
    dialog = await _open_add_dialog(page, base_url)
    await dialog.locator("#fp-place-pick-map-btn").click()
    await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")
    await page.wait_for_selector(".fp-map-pick-control")
    assert await page.locator(".fp-map-pick-marker").count() == 1


async def test_pick_on_map_click_sets_lat_lon_fields(page, base_url):
    dialog = await _open_add_dialog(page, base_url)
    before_lat = await dialog.locator("#fp-place-lat").input_value()
    before_lon = await dialog.locator("#fp-place-lon").input_value()

    await dialog.locator("#fp-place-pick-map-btn").click()
    await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")
    map_box = await page.locator("#map").bounding_box()
    # Away from the top-left zoom control and the bottom-left pick-mode
    # control (both corners), so this lands on plain map surface.
    x = map_box["x"] + map_box["width"] * 0.65
    y = map_box["y"] + map_box["height"] * 0.35
    await page.mouse.click(x, y)

    await page.locator(".fp-map-pick-control").get_by_text("Set location", exact=True).click()
    await page.wait_for_selector("#fp-place-dialog[open]")

    after_lat = await dialog.locator("#fp-place-lat").input_value()
    after_lon = await dialog.locator("#fp-place-lon").input_value()
    assert (after_lat, after_lon) != (before_lat, before_lon)


async def test_pick_on_map_cancel_reopens_the_dialog_unchanged(page, base_url):
    dialog = await _open_add_dialog(page, base_url)
    await dialog.locator("#fp-place-name").fill("Cancelled Pick")
    before_lat = await dialog.locator("#fp-place-lat").input_value()

    await dialog.locator("#fp-place-pick-map-btn").click()
    await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")
    map_box = await page.locator("#map").bounding_box()
    x = map_box["x"] + map_box["width"] * 0.7
    y = map_box["y"] + map_box["height"] * 0.3
    await page.mouse.click(x, y)
    await page.locator(".fp-map-pick-control").get_by_text("Cancel", exact=True).click()

    await page.wait_for_selector("#fp-place-dialog[open]")
    assert await dialog.locator("#fp-place-name").input_value() == "Cancelled Pick"
    assert await dialog.locator("#fp-place-lat").input_value() == before_lat


async def test_pick_on_map_keyboard_nudge_moves_the_point(page, base_url):
    """N13's keyboard fallback: no mouse at all -- the marker starts focused
    (at the point already in the fields), and an arrow key alone must move
    it before Enter confirms."""
    dialog = await _open_add_dialog(page, base_url)
    before_lon = float(await dialog.locator("#fp-place-lon").input_value())

    await dialog.locator("#fp-place-pick-map-btn").click()
    await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")
    marker = page.locator(".fp-map-pick-marker")
    await marker.wait_for(state="visible")
    assert await marker.evaluate("(el) => el === document.activeElement"), (
        "the marker must be focused as soon as pick mode starts"
    )

    await page.keyboard.press("ArrowRight")
    await page.keyboard.press("Enter")
    await page.wait_for_selector("#fp-place-dialog[open]")

    after_lon = float(await dialog.locator("#fp-place-lon").input_value())
    assert after_lon > before_lon


async def test_pick_on_map_escape_cancels(page, base_url):
    dialog = await _open_add_dialog(page, base_url)
    await dialog.locator("#fp-place-pick-map-btn").click()
    await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")
    marker = page.locator(".fp-map-pick-marker")
    await marker.wait_for(state="visible")

    await page.keyboard.press("Escape")
    await page.wait_for_selector("#fp-place-dialog[open]")
    # The picker's own layers must be gone, not just hidden behind the dialog.
    assert await page.locator(".fp-map-pick-control").count() == 0

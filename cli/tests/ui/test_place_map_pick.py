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

from .test_places_list import _wait_for_map_settled

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _places_tab_selector(width: int | None) -> str:
    """Under 600px the top nav is hidden and the bottom tab bar drives tabs
    instead (same split test_a11y.py's own scan uses) -- UAT7-N03's 375px
    viewport test needs the mobile selector, every other caller here stays on
    the desktop nav it always used."""
    if width and width < 600:
        return '.fp-tabbar [data-tabbar-tab="places"]'
    return 'button[data-tab="places"]'


async def _open_add_dialog(page, base_url, width=None):
    await page.goto(base_url + "/")
    # showAddDialog() reads map.getCenter() at click time, but bootDashboard()'s
    # setDefaultView() fit (real device fixes -> saved places -> world view)
    # runs asynchronously behind several awaits main.js's boot chain does after
    # #fp-add-place-btn is already wired and clickable -- a click landing in
    # that window opened the dialog (and any "Pick on map" started from it) at
    # map.js's WORLD_VIEW_CENTER [20, 0] default instead of the real location
    # (CI run 36258885493). test_places_list.py hit the same boot-vs-click race
    # (CI run 36140185227) and fixed it with these same two waits.
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")
    await _wait_for_map_settled(page)
    await page.click(_places_tab_selector(width))
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


async def test_add_dialog_defaults_enter_1_exit_2(page, base_url):
    """UAT7-N01: D17 pins enter=1, exit=2 (places/repo.py create_place's own
    defaults). The dialog used to default "Enter confirmations" to 2, so
    every place made through the UI needed two fixes to confirm an arrival."""
    dialog = await _open_add_dialog(page, base_url)
    assert await dialog.locator("#fp-place-enter").input_value() == "1"
    assert await dialog.locator("#fp-place-exit").input_value() == "2"


@pytest.mark.parametrize("width,height", ((1280, 800), (375, 812)))
async def test_pick_on_map_controls_stay_within_the_viewport(page, base_url, width, height):
    """UAT7-N03: bottomleft ran the control off the bottom of an 870px-tall
    map at 1280x800, leaving only the first instructions line on screen -- a
    mouse user had to scroll to find "Set location"/"Cancel" at all. topright
    plus scrolling the map into view on entering pick mode (places_dialog.js's
    beginMapPick) must keep both buttons on screen with no scroll, on both the
    desktop and phone tiers this app ships.
    """
    await page.set_viewport_size({"width": width, "height": height})
    dialog = await _open_add_dialog(page, base_url, width=width)
    await dialog.locator("#fp-place-pick-map-btn").click()
    await page.wait_for_selector(".fp-map-pick-control")

    control = page.locator(".fp-map-pick-control")
    for label in ("Set location", "Cancel"):
        box = await control.get_by_text(label, exact=True).bounding_box()
        assert box is not None, f"{label!r} has no box"
        assert box["x"] >= 0 and box["y"] >= 0, f"{label!r} is off the top/left edge: {box}"
        assert box["x"] + box["width"] <= width, f"{label!r} runs past the right edge: {box}"
        assert box["y"] + box["height"] <= height, f"{label!r} runs past the bottom edge: {box}"


async def test_pick_on_map_shows_the_picked_coordinates(page, base_url):
    """UAT7-N12: "Location set from the map." hid a wrong pick until the place
    was already saved -- the status line must show the actual coordinates."""
    dialog = await _open_add_dialog(page, base_url)
    await dialog.locator("#fp-place-pick-map-btn").click()
    await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")
    map_box = await page.locator("#map").bounding_box()
    x = map_box["x"] + map_box["width"] * 0.65
    y = map_box["y"] + map_box["height"] * 0.35
    await page.mouse.click(x, y)
    await page.locator(".fp-map-pick-control").get_by_text("Set location", exact=True).click()
    await page.wait_for_selector("#fp-place-dialog[open]")

    status = await page.locator("#fp-place-locator-status").inner_text()
    assert status.startswith("Location:")
    lat = await dialog.locator("#fp-place-lat").input_value()
    lon = await dialog.locator("#fp-place-lon").input_value()
    assert f"{float(lat):.4f}" in status
    assert f"{float(lon):.4f}" in status


async def test_radius_number_input_stays_in_sync_with_the_slider(page, base_url):
    """UAT7-N12: a slider alone gave no precise readout and no way to type an
    exact metre value -- the number box next to it must move the slider (and
    vice versa), each live."""
    dialog = await _open_add_dialog(page, base_url)
    slider = dialog.locator("#fp-place-radius")
    number = dialog.locator("#fp-place-radius-number")

    await slider.evaluate(
        "(el) => { el.value = '500'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
    )
    assert await number.input_value() == "500"

    await number.fill("750")
    assert await slider.input_value() == "750"


async def test_pick_on_map_radius_handle_resizes_the_circle(page, base_url):
    """UAT7-N12: the pick-mode circle can be resized on the map itself, not
    only from the dialog's own slider (which is not even on screen while the
    dialog is closed for the pick) -- a drag handle sits on the circle's east
    edge and dragging it changes the radius that "Set location" hands back."""
    dialog = await _open_add_dialog(page, base_url)
    before_radius = await dialog.locator("#fp-place-radius").input_value()

    await dialog.locator("#fp-place-pick-map-btn").click()
    await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")
    handle = page.locator(".fp-map-pick-radius-handle")
    await handle.wait_for(state="visible")
    box = await handle.bounding_box()
    start_x, start_y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    await page.mouse.move(start_x + 80, start_y, steps=5)
    await page.mouse.up()

    await page.locator(".fp-map-pick-control").get_by_text("Set location", exact=True).click()
    await page.wait_for_selector("#fp-place-dialog[open]")

    after_radius = await dialog.locator("#fp-place-radius").input_value()
    assert after_radius != before_radius

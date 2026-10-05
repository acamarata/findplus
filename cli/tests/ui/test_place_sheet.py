"""Browser tests for the place sheet (U5): the map stays visible while a place is edited.

Seed data (cli/tests/ui/conftest.py): same throwaway install as test_places.py,
map centred near (41.1, -80.1). The sheet is a non-modal <dialog>: the circle and
centre marker follow the radius, colour and centre live; "Use map centre" and
"Pick on map" work without leaving it.
"""

from __future__ import annotations

import pytest

from .test_places_list import _wait_for_map_settled

pytestmark = pytest.mark.asyncio(loop_scope="session")

# The live preview circle: an SVG path Leaflet does not mark interactive.
PREVIEW = ".leaflet-overlay-pane path:not(.leaflet-interactive)"


async def _open_add_dialog(page, base_url, width=None):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")
    await _wait_for_map_settled(page)
    tab = (
        '.fp-tabbar [data-tabbar-tab="places"]'
        if width and width < 600
        else 'button[data-tab="places"]'
    )
    await page.click(tab)
    await page.click("#fp-add-place-btn")
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")
    return dialog


async def test_the_sheet_is_non_modal_with_a_pin_and_circle_on_the_map(page, base_url):
    dialog = await _open_add_dialog(page, base_url)
    assert await dialog.get_attribute("data-sheet") == "1"
    assert (
        await page.evaluate("document.querySelector('#fp-place-dialog').matches(':modal')") is False
    )
    assert await page.locator(".fp-map-pick-marker").count() == 1
    assert await page.locator(PREVIEW).count() == 1
    assert await page.locator(".fp-map-pick-radius-handle").count() == 1


async def test_the_circle_follows_the_radius_box(page, base_url):
    dialog = await _open_add_dialog(page, base_url)
    before = (await page.locator(PREVIEW).bounding_box())["width"]
    await dialog.locator("#fp-place-radius-number").fill("300")
    after = (await page.locator(PREVIEW).bounding_box())["width"]
    assert after > before * 2


async def test_use_map_centre_moves_the_pin_without_closing_the_sheet(page, base_url):
    dialog = await _open_add_dialog(page, base_url)
    before = await dialog.locator("#fp-place-lat").input_value()
    box = await page.locator("#map").bounding_box()
    await page.mouse.move(box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.4)
    await page.mouse.down()
    await page.mouse.move(box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.7, steps=6)
    await page.mouse.up()
    await dialog.locator("#fp-place-use-centre-btn").click()
    assert await dialog.locator("#fp-place-lat").input_value() != before
    assert await dialog.get_attribute("open") is not None


async def test_pick_on_map_is_one_click_on_the_visible_map(page, base_url):
    dialog = await _open_add_dialog(page, base_url)
    before = (
        await dialog.locator("#fp-place-lat").input_value(),
        await dialog.locator("#fp-place-lon").input_value(),
    )
    button = dialog.locator("#fp-place-pick-map-btn")
    await button.click()
    assert await button.get_attribute("aria-pressed") == "true"
    box = await page.locator("#map").bounding_box()
    await page.mouse.click(box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.3)
    assert await button.get_attribute("aria-pressed") == "false"
    assert await dialog.get_attribute("open") is not None
    after = (
        await dialog.locator("#fp-place-lat").input_value(),
        await dialog.locator("#fp-place-lon").input_value(),
    )
    assert after != before
    status = await page.locator("#fp-place-locator-status").inner_text()
    assert status.startswith("Location:") and f"{float(after[0]):.4f}" in status


async def test_arrow_keys_nudge_the_pin(page, base_url):
    dialog = await _open_add_dialog(page, base_url)
    before = float(await dialog.locator("#fp-place-lon").input_value())
    await page.locator(".fp-map-pick-marker").focus()
    await page.keyboard.press("ArrowRight")
    assert float(await dialog.locator("#fp-place-lon").input_value()) > before


async def test_radius_handle_resizes_the_circle_and_the_fields(page, base_url):
    dialog = await _open_add_dialog(page, base_url)
    before = await dialog.locator("#fp-place-radius-number").input_value()
    handle = page.locator(".fp-map-pick-radius-handle")
    box = await handle.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    await page.mouse.move(x, y)
    await page.mouse.down()
    await page.mouse.move(x + 60, y, steps=5)
    await page.mouse.up()
    assert await dialog.locator("#fp-place-radius-number").input_value() != before


async def test_escape_and_cancel_remove_the_preview(page, base_url):
    await _open_add_dialog(page, base_url)
    await page.locator("#fp-place-name").focus()
    await page.keyboard.press("Escape")
    await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")
    await page.wait_for_function("() => !document.querySelector('.fp-map-pick-marker')")
    assert await page.locator(PREVIEW).count() == 0
    assert await page.evaluate("!document.body.classList.contains('fp-place-sheet-open')")


async def test_the_colour_picker_is_the_twelve_palette_swatches_only(page, base_url):
    dialog = await _open_add_dialog(page, base_url)
    assert await dialog.locator(".fp-color-swatch").count() == 12
    assert await dialog.locator("input[type=color]").count() == 0


async def test_save_stays_in_view_and_the_map_is_above_the_phone_sheet(page, base_url):
    await page.set_viewport_size({"width": 375, "height": 812})
    dialog = await _open_add_dialog(page, base_url, width=375)
    sheet = await dialog.bounding_box()
    assert sheet["y"] + sheet["height"] <= 812 and sheet["width"] == 375
    map_box = await page.locator("#map").bounding_box()
    assert map_box["height"] > 150 and map_box["y"] + map_box["height"] <= sheet["y"] + 1
    save = await page.get_by_role("button", name="Save", exact=True).bounding_box()
    assert save["y"] + save["height"] <= 812
    assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


async def test_a_failed_places_load_is_one_plain_sentence_with_retry(page, base_url):
    async def fail(route):
        await route.fulfill(status=500, json={"detail": "boom"})

    await page.route("**/api/places", fail)
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]")
    await page.click('button[data-tab="places"]')
    pane = page.locator("#fp-places-list [data-pane-error]")
    await pane.wait_for()
    text = await pane.inner_text()
    assert "Find+ could not load your places. Try again." in text
    assert "boom" not in text, "raw server text stays behind Details"
    add = page.locator("#fp-add-place-btn")
    assert await add.is_disabled()
    assert "Retry" in await page.locator("#fp-places-add-reason").inner_text()
    await page.unroute("**/api/places")
    await pane.get_by_role("button", name="Retry").click()
    await pane.wait_for(state="detached")
    assert await add.is_enabled()
    assert await page.locator("#fp-places-add-reason").is_hidden()


async def test_add_dialog_defaults_enter_1_exit_2(page, base_url):
    """UAT7-N01: D17 pins enter=1, exit=2 (places/repo.py create_place's own defaults)."""
    dialog = await _open_add_dialog(page, base_url)
    assert await dialog.locator("#fp-place-enter").input_value() == "1"
    assert await dialog.locator("#fp-place-exit").input_value() == "2"
    assert await page.locator("#fp-place-advanced").get_attribute("open") is None


async def test_radius_number_input_stays_in_sync_with_the_slider(page, base_url):
    """UAT7-N12: the number box moves the slider and the slider moves the box, each live."""
    dialog = await _open_add_dialog(page, base_url)
    slider = dialog.locator("#fp-place-radius")
    number = dialog.locator("#fp-place-radius-number")
    await slider.evaluate(
        "(el) => { el.value = '500'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
    )
    assert await number.input_value() == "500"
    await number.fill("750")
    assert await slider.input_value() == "500"
    assert await number.input_value() == "750"

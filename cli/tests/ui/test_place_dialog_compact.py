"""The place dialog after UAT 11 and 21: radius, kind note, alert box, compact layout."""

from __future__ import annotations

import json

import pytest

from ._notify_helpers import open_add_dialog

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _capture(page):
    sent: list[dict] = []

    async def handler(route):
        if route.request.method == "POST":
            sent.append(json.loads(route.request.post_data))
            await route.fulfill(
                status=409, json={"detail": "A place with that name already exists"}
            )
        else:
            await route.continue_()

    await page.route("**/api/places", handler)
    return sent


async def _open_on_phone(page, base_url):
    """Under 600 px the top nav is hidden; the bottom tab bar drives the tabs."""
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]")
    await page.click('.fp-tabbar [data-tabbar-tab="places"]')
    await page.click("#fp-add-place-btn")
    await page.wait_for_selector("#fp-place-dialog[open]")


async def test_a_new_place_starts_at_one_hundred_metres(page, base_url):
    await open_add_dialog(page, base_url)
    assert await page.locator("#fp-place-radius-number").input_value() == "100"
    assert await page.locator("#fp-place-radius").input_value() == "100"
    assert await page.locator("#fp-place-radius-warn").is_hidden()
    assert "Recommended: 100 m or more" in await page.inner_text("#fp-place-radius-hint")


async def test_the_slider_covers_fifty_to_five_hundred_and_the_box_goes_higher(page, base_url):
    await open_add_dialog(page, base_url)
    slider = page.locator("#fp-place-radius")
    assert (await slider.get_attribute("min"), await slider.get_attribute("max")) == ("50", "500")
    await page.fill("#fp-place-radius-number", "200")
    assert await slider.input_value() == "200"
    await page.fill("#fp-place-radius-number", "50")
    assert await slider.input_value() == "50"
    assert await page.locator("#fp-place-radius-warn").is_visible()
    await page.fill("#fp-place-radius-number", "1500")
    assert await slider.input_value() == "500"


async def test_a_radius_above_the_slider_is_saved_as_typed(page, base_url):
    sent = await _capture(page)
    await open_add_dialog(page, base_url)
    await page.fill("#fp-place-name", "Big Field")
    await page.fill("#fp-place-radius-number", "1500")
    await page.get_by_role("button", name="Save", exact=True).click()
    await page.wait_for_function(
        "() => document.getElementById('fp-place-dialog-error').textContent.length > 0"
    )
    assert sent[0]["radius_meters"] == 1500


async def test_the_guessed_note_waits_for_a_name(page, base_url):
    await open_add_dialog(page, base_url)
    hint = page.locator("#fp-place-kind-hint")
    assert await hint.is_hidden()
    await page.fill("#fp-place-name", "Grandma's")
    assert "guessed this from the name" in await hint.inner_text()
    await page.fill("#fp-place-name", "Park")
    assert await hint.is_hidden(), "no kind was guessed from that name"
    await page.fill("#fp-place-name", "")
    assert await hint.is_hidden()


async def test_the_alert_box_is_ticked_by_default(page, base_url):
    await open_add_dialog(page, base_url)
    assert await page.is_checked("#fp-place-notify")


async def test_save_is_in_view_at_720_px_tall(page, base_url):
    await page.set_viewport_size({"width": 1280, "height": 720})
    await open_add_dialog(page, base_url)
    save = page.get_by_role("button", name="Save", exact=True)
    box = await save.bounding_box()
    assert box and box["y"] + box["height"] <= 720
    dialog = await page.locator("#fp-place-dialog").bounding_box()
    assert dialog["height"] <= 720


async def test_save_is_in_view_on_a_phone(page, base_url):
    await page.set_viewport_size({"width": 375, "height": 700})
    await _open_on_phone(page, base_url)
    box = await page.get_by_role("button", name="Save", exact=True).bounding_box()
    assert box and box["y"] + box["height"] <= 700
    assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


async def test_right_hand_sheet_on_desktop_bottom_sheet_on_a_phone(page, base_url):
    await page.set_viewport_size({"width": 1280, "height": 900})
    await open_add_dialog(page, base_url)
    dlg = page.locator("#fp-place-dialog")
    assert await dlg.get_attribute("data-sheet") == "1"
    box = await dlg.bounding_box()
    assert box["x"] + box["width"] == 1280 and box["width"] <= 400
    assert (
        await page.locator(".fp-place-cols").evaluate("(e) => getComputedStyle(e).display")
        == "block"
    )
    # The map stays visible and un-dimmed to the sheet's left.
    map_box = await page.locator("#map").bounding_box()
    assert map_box["x"] + map_box["width"] <= box["x"] + 1
    await dlg.get_by_role("button", name="Cancel").click()
    await page.set_viewport_size({"width": 375, "height": 800})
    await _open_on_phone(page, base_url)
    box = await dlg.bounding_box()
    assert box["y"] + box["height"] == 800 and box["width"] == 375
    map_box = await page.locator("#map").bounding_box()
    assert map_box["y"] + map_box["height"] <= box["y"] + 1, (
        "the map is visible above the bottom sheet"
    )

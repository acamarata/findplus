"""Devices dialog 1.3 (U13): a row edits in place, with a searchable icon grid and
a footer that never leaves the screen.

Seed (cli/tests/ui/conftest.py): TAG-HOME is labelled and tracked; there are four
devices in all.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

HOME = '.device-row[data-device-id="TAG-HOME"]'


async def _open_devices(page, base_url, width=1400, height=900):
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container", state="attached")
    await page.evaluate("document.getElementById('btn-devices').click()")
    await page.wait_for_selector("#device-modal:not(.hidden)")
    await page.wait_for_selector(".device-row")


async def _open_editor(page, row=HOME):
    await page.click(f"{row} .fp-device-edit")
    await page.wait_for_selector(f"{row}.is-editing .device-edit")


async def test_editing_a_row_opens_no_second_dialog(page, base_url):
    await _open_devices(page, base_url)
    await _open_editor(page)
    assert await page.locator("dialog[open]").count() == 0
    assert await page.locator("#device-modal").is_visible()


async def test_only_one_row_edits_at_a_time(page, base_url):
    await _open_devices(page, base_url)
    await _open_editor(page)
    others = page.locator(".device-row:not([data-device-id='TAG-HOME']) .fp-device-edit")
    await others.first.click()
    await page.wait_for_function("document.querySelectorAll('.device-edit').length === 1")
    assert await page.locator(f"{HOME} .device-edit").count() == 0


async def test_escape_closes_the_editor_not_the_dialog(page, base_url):
    await _open_devices(page, base_url)
    await _open_editor(page)
    await page.keyboard.press("Escape")
    await page.wait_for_selector(".device-edit", state="detached")
    assert await page.locator("#device-modal").is_visible()
    assert await page.evaluate("document.activeElement.classList.contains('fp-device-edit')")
    assert await page.get_attribute(f"{HOME} .fp-device-edit", "aria-expanded") == "false"


async def test_icon_search_filters_and_says_when_nothing_matches(page, base_url):
    await _open_devices(page, base_url)
    await _open_editor(page)
    box = page.get_by_role("searchbox", name="Search icons")
    await box.fill("key")
    swatches = page.locator(".device-edit .fp-icon-picker .fp-icon-swatch:visible")
    names = await swatches.evaluate_all("els => els.map(e => e.getAttribute('aria-label'))")
    assert names and all("key" in n for n in names), names
    await box.fill("zzzzqqqq")
    assert await swatches.count() == 0
    assert "No icon matches" in await page.locator(".fp-icon-search-empty").inner_text()
    await box.fill("")
    assert await swatches.count() > 20


async def test_upload_is_a_button_and_the_file_input_is_not_visible(page, base_url):
    await _open_devices(page, base_url)
    await _open_editor(page)
    await page.get_by_role("button", name="Upload your own").wait_for(state="visible")
    box = await page.locator(".device-edit .fp-custom-icon-upload input").bounding_box()
    assert box is None or box["width"] <= 1


@pytest.mark.parametrize(("width", "height"), [(1400, 700), (375, 812)])
async def test_the_footer_stays_on_screen_while_a_row_is_editing(page, base_url, width, height):
    await _open_devices(page, base_url, width, height)
    await _open_editor(page)
    for sel in ("#btn-save-devices", "#btn-track-all", "#btn-refresh-devices"):
        box = await page.locator(sel).bounding_box()
        assert box is not None and box["y"] >= 0 and box["y"] + box["height"] <= height, (sel, box)


async def test_saving_a_label_keeps_unsaved_ticks(page, base_url):
    """The row's tracking tick is a separate, unsaved choice; an inline save must
    re-draw the list without throwing it away."""
    await _open_devices(page, base_url)
    tick = f"{HOME} input[type=checkbox]"
    was = await page.is_checked(tick)
    await page.set_checked(tick, not was)
    await _open_editor(page)
    original = await page.input_value("#fp-device-inline-label")
    await page.fill("#fp-device-inline-label", "Ticked Keys")
    try:
        await page.click(".device-edit button:has-text('Save changes')")
        await page.locator(f"{HOME} .d-name", has_text="Ticked Keys").wait_for()
        assert await page.is_checked(tick) is (not was)
    finally:
        await page.request.patch(
            base_url + "/api/devices/TAG-HOME",
            data=json.dumps({"label": original}),
            headers={"Content-Type": "application/json"},
        )

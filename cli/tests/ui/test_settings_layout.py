"""Playwright browser tests for Settings dialog layout, focus and theme
(UAT6-N29, UAT6-N20): units used to sit far from their inputs, the two
number fields did not line up, About showed the package identifier instead
of the display name, and Set PIN stranded focus on <body> (which also broke
Escape, since dialog-trap.js's keydown listener lives on #settings-modal).
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

PIN = "864213"


async def _open_settings(page, base_url) -> None:
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")
    await page.click("#btn-settings")
    await page.wait_for_selector("#settings-modal[data-loaded='true']")


async def _clear_pin_if_configured(page, base_url) -> None:
    resp = await page.request.get(base_url + "/api/settings")
    if (await resp.json()).get("pin_configured"):
        await page.request.delete(
            base_url + "/api/settings/pin",
            data=json.dumps({"current_pin": PIN}),
            headers={"Content-Type": "application/json"},
        )


async def test_poll_interval_and_retention_units_sit_beside_their_inputs(page, base_url):
    await _open_settings(page, base_url)
    poll_input = await page.locator("#setting-poll-interval").bounding_box()
    poll_unit = await page.locator("#setting-poll-interval + span").bounding_box()
    retention_input = await page.locator("#setting-retention-days").bounding_box()
    retention_unit = await page.locator("#setting-retention-days + span").bounding_box()

    # "Far" was the whole dialog width (space-between with 3 siblings); a
    # unit right beside its input is a few pixels of gap, not hundreds.
    assert poll_unit["x"] - (poll_input["x"] + poll_input["width"]) < 20
    assert retention_unit["x"] - (retention_input["x"] + retention_input["width"]) < 20


async def test_poll_interval_and_retention_inputs_share_one_baseline(page, base_url):
    await _open_settings(page, base_url)
    poll_box = await page.locator("#setting-poll-interval").bounding_box()
    retention_box = await page.locator("#setting-retention-days").bounding_box()
    assert abs(poll_box["x"] - retention_box["x"]) < 2, "the two inputs no longer share an x"


async def test_poll_interval_and_retention_inputs_are_equal_width(page, base_url):
    """UAT7-N18: with no width rule of their own the two number inputs sized
    themselves independently and rendered a few pixels apart."""
    await _open_settings(page, base_url)
    poll_box = await page.locator("#setting-poll-interval").bounding_box()
    retention_box = await page.locator("#setting-retention-days").bounding_box()
    diff = abs(poll_box["width"] - retention_box["width"])
    assert diff < 2, "the two inputs are different widths"


async def test_retention_placeholder_says_keep_all_with_no_separate_hint(page, base_url):
    """UAT7-N18: "days (blank = forever)" used to be spread across the unit
    text, a dedicated hint line under the field, AND the explanatory note
    below it -- three places saying the same thing. The field's own
    placeholder now says "keep all" and the note is the only explanation
    left; there is no more separate hint paragraph."""
    await _open_settings(page, base_url)
    unit_text = await page.locator("#setting-retention-days + span").inner_text()
    assert unit_text.strip() == "days"
    placeholder = await page.locator("#setting-retention-days").get_attribute("placeholder")
    assert placeholder == "keep all"
    assert await page.locator("p.setting-row-hint").count() == 0


async def test_about_shows_the_display_name_not_the_identifier(page, base_url):
    await _open_settings(page, base_url)
    about = await page.locator("#settings-about").inner_text()
    assert about.startswith("Find+ "), about
    assert "findplus" not in about


async def test_theme_selector_offers_system(page, base_url):
    await _open_settings(page, base_url)
    values = await page.eval_on_selector_all(
        "#setting-theme option", "opts => opts.map(o => o.value)"
    )
    assert "system" in values
    assert set(values) == {"dark", "light", "system"}

    try:
        await page.select_option("#setting-theme", "system")
        resp = await page.request.get(base_url + "/api/settings")
        assert (await resp.json())["theme"] == "system"
    finally:
        await page.request.patch(
            base_url + "/api/settings",
            data=json.dumps({"theme": "dark"}),
            headers={"Content-Type": "application/json"},
        )


async def test_set_pin_moves_focus_into_view_and_escape_still_closes(page, base_url):
    """UAT6-N29: Set PIN hides #lock-not-set (its own button's section) and
    reveals #lock-is-set. Focus must land somewhere visible in that section,
    and Escape -- which only reaches dialog-trap.js's listener when focus is
    still inside #settings-modal -- must still close the dialog afterwards.
    """
    await _clear_pin_if_configured(page, base_url)
    try:
        await _open_settings(page, base_url)
        await page.wait_for_selector("#lock-not-set:not(.hidden)")
        await page.fill("#new-pin", PIN)
        await page.fill("#confirm-pin", PIN)
        await page.click("#btn-set-pin")

        await page.wait_for_selector("#lock-is-set:not(.hidden)")
        focused_id = await page.evaluate("document.activeElement.id")
        assert focused_id == "setting-lock-enabled", focused_id
        assert await page.is_visible(f"#{focused_id}")

        await page.keyboard.press("Escape")
        await page.wait_for_function(
            "document.getElementById('settings-modal').classList.contains('hidden')"
        )
    finally:
        await _clear_pin_if_configured(page, base_url)

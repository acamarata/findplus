"""Group dialog layout: pickers on a cold open, name and members first.

Split from test_groups_dialog.py at the 300-line cap.
"""

from __future__ import annotations

import pytest

from .test_groups_dialog import _open_add_dialog, _open_groups_tab

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_icon_and_color_pickers_populate_on_a_cold_open(page, base_url):
    """Visual gate W3 finding 1: the closed colour button had no content at
    all (build-notes.md § W3 gate fixes), and nothing exercised the colour
    popover before. This is a fresh page (no dialog opened earlier in the
    test), so ensurePickers() runs for the first time here — the "cold page,
    no prior sprite fetch" case the fix's root-cause note calls out."""
    await _open_groups_tab(page, base_url)
    await page.click("#fp-add-group-btn")
    await page.wait_for_selector("#fp-group-dialog[open]")

    # Closed state: both trigger buttons show a swatch, not an empty pill.
    icon_html = await page.locator("#fp-group-icon-btn").inner_html()
    color_bg = await page.locator("#fp-group-color-btn").evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )
    assert icon_html.strip()
    assert color_bg not in ("rgba(0, 0, 0, 0)", "transparent")

    await page.click("#fp-group-icon-btn")
    icon_count = await page.locator("#fp-group-icon-popover .fp-icon-swatch").count()
    assert icon_count >= 40, icon_count
    # The icon grid is tall enough to sit over the colour row below it; close
    # it the same way a user would (re-click its own trigger) before opening
    # the colour popover, rather than clicking through it.
    await page.click("#fp-group-icon-btn")
    await page.wait_for_selector("#fp-group-icon-popover", state="hidden")

    await page.click("#fp-group-color-btn")
    color_count = await page.locator("#fp-group-color-popover .fp-color-swatch").count()
    assert color_count == 12, color_count


async def test_name_and_members_first_the_rest_under_advanced(page, base_url):
    """U11: Name and Members first; quorum, radius and stale sit in a collapsed Advanced."""
    await _open_add_dialog(page, base_url)
    advanced = page.locator("#fp-group-advanced")
    assert await advanced.get_attribute("open") is None
    assert not await page.locator("#fp-group-quorum").is_visible()
    name_y = (await page.locator("#fp-group-name").bounding_box())["y"]
    members_y = (await page.locator("#fp-group-members").bounding_box())["y"]
    advanced_y = (await advanced.bounding_box())["y"]
    assert name_y < members_y < advanced_y
    await page.click("#fp-group-advanced summary")
    for field in ("#fp-group-quorum", "#fp-group-radius", "#fp-group-stale"):
        assert await page.locator(field).is_visible()
    assert "Ignore a tracker" in await page.locator("label[for=fp-group-stale]").inner_text()
    # No inner scroller on the member list.
    overflow = await page.locator("#fp-group-members").evaluate(
        "(e) => getComputedStyle(e).overflowY"
    )
    assert overflow in ("visible", "")

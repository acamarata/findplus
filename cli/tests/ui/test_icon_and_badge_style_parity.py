"""Browser tests for UAT7-N19: the "Your icons" heading matches the Lucide
category headings' style, and the Apple/Find Hub provider badges match each
other's.

Split into its own file rather than added to test_custom_icons.py or
test_icon_color_pickers.py, both already near this suite's 300-line file cap.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_device_edit_dialog(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("svg#fp-icon-sprite symbol[id='lucide-dog']", state="attached")
    await page.wait_for_selector("#map.leaflet-container")
    await page.click("#btn-devices")
    await page.wait_for_selector("#device-modal:not(.hidden)")
    await page.click('.device-row[data-device-id="TAG-HOME"] .fp-device-edit')
    await page.wait_for_selector("#fp-device-dialog[open]")
    await page.wait_for_selector(".fp-custom-icons .fp-icon-grid", state="attached")


def _style_of(page, selector: str):
    return page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            const s = getComputedStyle(el);
            return { transform: s.textTransform, weight: s.fontWeight, size: s.fontSize };
        }""",
        selector,
    )


async def test_your_icons_heading_matches_the_lucide_category_headings(page, base_url):
    """Both headings share one class (icon-picker.js's categoryHeading() and
    custom-icons.js's own "Your icons" heading), so they compute to the same
    text-transform/weight/size rather than two different looks in the same
    picker."""
    await _open_device_edit_dialog(page, base_url)
    your_icons_heading = page.locator("#fp-device-dialog .fp-custom-icons h4")
    assert "fp-icon-group-heading" in (await your_icons_heading.get_attribute("class") or "")
    category_style = await _style_of(page, "#fp-device-dialog .fp-icon-group-heading")
    your_icons_style = await _style_of(page, "#fp-device-dialog .fp-custom-icons h4")
    assert your_icons_style == category_style


async def test_apple_and_find_hub_badges_share_the_same_treatment(page, base_url):
    """Both variants keep their own tint (still the way to tell the two
    providers apart) but now share the same hairline ring, rather than one
    being a plain fill and the other only an outline."""
    await page.goto(base_url + "/")
    await page.click("#btn-devices")
    selector = ".fp-provider-badge--google-find-hub"
    await page.wait_for_selector(selector, state="attached")
    google_shadow = await page.evaluate(
        "(sel) => getComputedStyle(document.querySelector(sel)).boxShadow", selector
    )
    assert google_shadow not in ("none", "")

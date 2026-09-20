"""Icon/colour popover panel checks, split out of test_groups_dialog.py at
the 300-line file cap (same move test_groups_dialog_purge.py made).

Visual gate W3 round 2: the popover's positioned ancestor (`.fp-picker-
control`) is only as wide as its trigger button, so an absolutely positioned
panel anchored there can shrink to one column, or -- once width-capped --
still run past the viewport's right edge on a narrow dialog. These cases
assert every swatch actually lands inside both the viewport and the dialog's
own padding box, at desktop and phone widths.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

# (trigger id, popover id, swatch selector) per popover kind -- one test
# case per kind x width below covers "one browser test per popover".
POPOVERS = {
    "icon": ("fp-group-icon-btn", "fp-group-icon-popover", ".fp-icon-swatch"),
    "color": ("fp-group-color-btn", "fp-group-color-popover", ".fp-color-swatch"),
}


async def _assert_swatches_in_dialog(page, popover_id, swatch_class):
    """Every swatch's box must sit inside both the viewport and
    #fp-group-dialog's padding box (its border box inset by its own 1px
    border) -- the popover is a `position: absolute` overlay that can drift
    outside either without changing the dialog's own size."""
    viewport = page.viewport_size
    dialog = await page.locator("#fp-group-dialog").bounding_box()
    swatches = page.locator(f"#{popover_id} {swatch_class}")
    count = await swatches.count()
    assert count > 0
    for i in range(count):
        box = await swatches.nth(i).bounding_box()
        assert box is not None
        assert box["x"] >= 0 and box["y"] >= 0, box
        assert box["x"] + box["width"] <= viewport["width"], box
        assert box["y"] + box["height"] <= viewport["height"], box
        assert box["x"] >= dialog["x"] + 1, box
        assert box["y"] >= dialog["y"] + 1, box
        assert box["x"] + box["width"] <= dialog["x"] + dialog["width"] - 1, box
        assert box["y"] + box["height"] <= dialog["y"] + dialog["height"] - 1, box


@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize("kind", ["icon", "color"])
async def test_popover_swatches_fit_viewport_and_dialog(page, base_url, width, kind):
    btn_id, popover_id, swatch_class = POPOVERS[kind]
    await page.set_viewport_size({"width": width, "height": 800})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#fp-add-group-btn", state="attached")
    # `.fp-tabs` is CSS-hidden under 600px (test_a11y.py's own reason for the
    # same evaluate-click); the tab's content is unaffected by that rule.
    await page.evaluate("document.querySelector('.fp-tabs [data-tab=\"groups\"]').click()")
    await page.wait_for_selector(".fp-group-card, .fp-empty-state", state="attached")
    await page.wait_for_selector("#fp-add-group-btn", state="visible")
    await page.click("#fp-add-group-btn")
    await page.wait_for_selector("#fp-group-dialog[open]")
    await page.click(f"#{btn_id}")
    await _assert_swatches_in_dialog(page, popover_id, swatch_class)

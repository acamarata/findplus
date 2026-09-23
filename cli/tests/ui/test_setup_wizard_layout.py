"""Browser tests for the wizard's presentation fixes (R-P2-28, visual gate W4).

Purpose    : Pins R-P2-28 points 1, 2 and 6: the wizard renders inside a
             bounded, centred card; the Groups step's icon/colour pickers
             are popover triggers, not a bare grid; the delivery-log Status
             column stays inside the pane at 1280px. The axe matrix for the
             four touched steps closes the file.
Constraints: `live_server` is shared and assumes a finished setup, so every
             wizard test here restores the stamp in a `finally`, matching
             every sibling wizard test file.

Points 3 and 5 (WhatsApp inline setup, the Places-step disclaimer) and the
sign-in points moved to test_setup_wizard_notifications.py (E13 stage 2,
size cap).
"""

from __future__ import annotations

import json

import pytest
from axe_playwright_python.async_playwright import Axe

from .conftest import SEEDED_COMPLETED_AT, set_theme
from .test_a11y import AXE_OPTIONS, BLOCKING, _describe

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _set_completed_at(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _set_last_step(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.last_step",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _open_step(page, base_url, step):
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, step)
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)


@pytest.mark.parametrize("step", ["welcome", "groups", "notifications", "applock"])
async def test_wizard_card_is_bounded_and_centred_at_1280(page, base_url, step):
    """R-P2-28 point 1: max-width 720px, centred, not edge-to-edge."""
    await page.set_viewport_size({"width": 1280, "height": 900})
    try:
        await _open_step(page, base_url, step)
        box = await page.locator("#setup-view").bounding_box()
        assert box is not None
        assert box["width"] <= 760, box
        # Centred: roughly equal space on both sides of the 1280px viewport.
        left_gutter = box["x"]
        right_gutter = 1280 - (box["x"] + box["width"])
        assert abs(left_gutter - right_gutter) < 5, (left_gutter, right_gutter)

        # Every footer control stays inside the card, not spilling past it.
        next_box = await page.locator("#fp-wizard-next").bounding_box()
        assert next_box["x"] + next_box["width"] <= box["x"] + box["width"] + 1
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


@pytest.mark.parametrize("step", ["welcome", "groups", "notifications", "applock"])
async def test_wizard_has_no_horizontal_overflow_at_375(page, base_url, step):
    """R-P2-28 point 1: full-width with 16px gutters below 600px, never wider
    than the viewport (F1/F2 both only reproduced with real content on screen,
    so this walks the same four steps the 1280px check does)."""
    await page.set_viewport_size({"width": 375, "height": 800})
    try:
        await _open_step(page, base_url, step)
        overflow = await page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 1, f"{step}: {overflow}px of horizontal overflow"
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_groups_step_uses_popover_pickers_not_a_bare_grid(page, base_url):
    """R-P2-28 point 2 / F1: the icon and colour grids sit behind trigger
    buttons, like the group dialog's own fields, closed until clicked."""
    try:
        await _open_step(page, base_url, "groups")
        await page.wait_for_selector("#fp-setup-group-icon-btn", timeout=15000)

        assert await page.locator("#fp-setup-group-icon-popover").is_hidden()
        assert await page.locator("#fp-setup-group-color-popover").is_hidden()
        # The member checklist row uses the dialog's own class, not the wide
        # settings row (F1's root cause).
        await page.wait_for_selector(".fp-member-row", timeout=15000)
        assert await page.locator(".fp-member-row").count() >= 1

        await page.click("#fp-setup-group-icon-btn")
        await page.wait_for_selector("#fp-setup-group-icon-popover:not([hidden])", timeout=5000)
        assert await page.locator("#fp-setup-group-color-popover").is_hidden()

        # An open popover overlays whatever sits below it (real dropdown
        # behaviour), so a real user closes it — outside click, same path the
        # group dialog's own popovers use — before reaching the next trigger.
        await page.click("#fp-setup-groups-list")
        await page.wait_for_selector("#fp-setup-group-icon-popover", state="hidden", timeout=5000)

        await page.click("#fp-setup-group-color-btn")
        await page.wait_for_selector("#fp-setup-group-color-popover:not([hidden])", timeout=5000)
        assert await page.locator("#fp-setup-group-icon-popover").is_hidden()

        # Outside click closes whichever popover is open.
        await page.click("#fp-setup-groups-list")
        await page.wait_for_selector("#fp-setup-group-color-popover", state="hidden", timeout=5000)
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_wizard_map_controls_keep_leaflets_own_contrast_in_dark_theme(page, base_url):
    """UAT4 N37: #setup-view a (components.css) recolors every link inside
    the wizard card, including Leaflet's own zoom +/- and OSM attribution
    links once the Places step borrows the dashboard map into #setup-view --
    --badge-text is a pale blue in dark theme, unreadable against Leaflet's
    white control background. Pins the two override rules restoring exactly
    what leaflet.css itself sets."""
    try:
        await _open_step(page, base_url, "places")
        await set_theme(page, "dark")
        await page.wait_for_selector("#map .leaflet-control-zoom-in", timeout=15000)

        zoom_color = await page.locator("#map .leaflet-control-zoom-in").evaluate(
            "el => getComputedStyle(el).color"
        )
        attribution_color = await page.locator(
            "#map .leaflet-control-attribution a"
        ).first.evaluate("el => getComputedStyle(el).color")
        assert zoom_color == "rgb(0, 0, 0)", zoom_color
        assert attribution_color == "rgb(51, 51, 51)", attribution_color
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_deliveries_table_causes_no_horizontal_scroll_at_1280(page, base_url):
    """R-P2-28 point 6 / F6, updated for UAT2 U9: the table's own columns
    used to sit past the 380px side pane's edge at 1280, reachable only by
    scrolling the whole page. UAT2 found that fix (fixed pixel widths) was
    still unreadable in that same narrow pane -- U9's real fix is the
    `@container` card layout (components.css), which drops the header
    row entirely rather than fitting it, so this test's own job narrows to
    what still has to hold at 1280: no page-level horizontal scroll, and the
    pane is in card mode (thead hidden), not the old fixed-width table.

    Seed data carries no alert_deliveries rows (nothing here runs the
    poll/evaluate loop that would create one); card mode does not need a row
    to prove itself -- the thead's display alone does.
    """
    await page.set_viewport_size({"width": 1280, "height": 900})
    await page.goto(base_url + "/#dashboard")
    await page.wait_for_selector("#map.leaflet-container")
    await page.click('button[data-tab="alerts"]')
    await page.wait_for_selector("#fp-deliveries-table", state="attached", timeout=15000)

    thead_display = await page.locator("#fp-deliveries-table thead").evaluate(
        "el => getComputedStyle(el).display"
    )
    assert thead_display == "none", "the 380px pane at 1280 should be in card mode"

    page_overflow = await page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert page_overflow <= 1, page_overflow


#: The four steps R-P2-28 changed the layout/markup of.
WIZARD_AXE_STEPS = ("welcome", "groups", "notifications", "applock")


@pytest.mark.parametrize("theme", ("dark", "light"))
@pytest.mark.parametrize("step", WIZARD_AXE_STEPS)
async def test_no_serious_axe_violations_on_touched_wizard_steps(page, base_url, step, theme):
    """R-P2-28 build brief: keep the axe matrix at 0 serious including the
    wizard steps this ticket touched (the full wizard axe matrix, every step,
    is R-P2-26's E13-T1 — this covers only what changed here)."""
    try:
        await _open_step(page, base_url, step)
        await set_theme(page, theme)

        results = await Axe().run(page, options=AXE_OPTIONS)
        violations = results.response["violations"]
        for violation in violations:
            if violation.get("impact") not in BLOCKING:
                print(f"axe {_describe(violation, step, theme, 1280)}")
        blocking = [v for v in violations if v.get("impact") in BLOCKING]
        assert not blocking, "\n".join(_describe(v, step, theme, 1280) for v in blocking)
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)

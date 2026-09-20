"""Phone-width (<600px) layout regression tests (visual gate W2 fix loop).

Purpose    : .claude/phases/current/p2/reviews/visual-W2/*.png flagged three
             375px defects: the fixed bottom tab bar risked covering the last
             element of a tall tab, the rules/delivery-log tables and the
             Settings/Alerts form rows overflowed the viewport horizontally,
             and the Export "Download" button could wrap onto a row of its
             own away from the format/scope controls it belongs with.
Inputs     : live_server (conftest.py), no lock configured — same as
             test_a11y.py, a plain goto with no PIN.
Outputs    : none (assertions only).
Constraints: 375 is the iPhone SE/Mini class width test_a11y.py already pins
             as the phone-tier probe; no viewport narrower than that ships.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

PHONE_WIDTH = 375
PHONE_HEIGHT = 812


async def _open_tab(page, tab: str) -> None:
    await page.click(f'.fp-tabbar [data-tabbar-tab="{tab}"]')
    await page.wait_for_selector(f"#tab-{tab}:not([hidden])")
    await page.wait_for_timeout(150)


async def _open_settings(page) -> None:
    await page.click("#btn-more")
    await page.click('[data-relays-to="btn-settings"]')
    await page.wait_for_selector("#settings-modal:not(.hidden)")
    await page.wait_for_timeout(150)


# Scoped to the surfaces this fix loop touched (dashboard's export row,
# alerts' form rows and tables, settings' form rows) — not every tab. The
# Groups card row (.fp-group-card in web/components.css) has its own,
# pre-existing overflow at 375px unrelated to this ticket's three findings
# and belongs to whichever ticket owns web/app/groups.js.
@pytest.mark.parametrize("surface", ("dashboard", "alerts", "settings"))
async def test_no_horizontal_overflow_at_phone_width(page, base_url, surface):
    """No element pushes the page wider than the viewport at 375px.

    Caught the rules/delivery-log tables (7 and 6 columns) and the
    Settings/Alerts .setting-row inputs (190px min-width) both growing the
    page past its own width instead of scrolling within their own box.
    """
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")
    if surface == "alerts":
        await _open_tab(page, "alerts")
    elif surface == "settings":
        await _open_settings(page)

    width = await page.evaluate("document.documentElement.scrollWidth")
    assert width <= PHONE_WIDTH, (
        f"{surface}: page scrolls to {width}px at a {PHONE_WIDTH}px viewport"
    )


async def test_alerts_last_element_not_covered_by_tabbar(page, base_url):
    """The bottom tab bar sits over the end of the page; body's padding-bottom
    must keep the last rendered row above it, not under it."""
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")
    await _open_tab(page, "alerts")
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(150)

    tabbar_box = await page.locator(".fp-tabbar").bounding_box()
    last = page.locator("#tab-alerts *:visible").last
    await last.scroll_into_view_if_needed()
    last_box = await last.bounding_box()

    assert tabbar_box is not None and last_box is not None
    overlaps = last_box["y"] + last_box["height"] > tabbar_box["y"] and last_box["y"] < (
        tabbar_box["y"] + tabbar_box["height"]
    )
    assert not overlaps, f"last alerts element {last_box} overlaps the tab bar {tabbar_box}"


async def test_setting_rows_stack_label_above_input_at_phone_width(page, base_url):
    """A text/select .setting-row is a column (label, then a full-width
    control) below 600px, not squeezed onto one row (E9 settings dialog)."""
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")
    await _open_tab(page, "alerts")

    direction = await page.evaluate(
        """() => getComputedStyle(document.querySelector('#fp-webhook-section .setting-row'))
            .flexDirection"""
    )
    assert direction == "column"


async def test_rules_table_scrolls_within_its_own_wrapper(page, base_url):
    """The rules table overflows a 375px viewport; .fp-table-scroll should
    absorb that overflow itself rather than growing the page."""
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")
    await _open_tab(page, "alerts")

    sizes = await page.evaluate(
        """() => {
            const wrap = document.querySelector('#fp-rules-table').closest('.fp-table-scroll');
            return {scrollWidth: wrap.scrollWidth, clientWidth: wrap.clientWidth};
        }"""
    )
    assert sizes["clientWidth"] <= PHONE_WIDTH


async def test_export_download_button_joins_the_export_row(page, base_url):
    """The Download button is grouped with the format/scope controls
    (.export-group) so it wraps together with them, not onto an isolated
    row of its own away from the rest of the export controls."""
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")

    same_group = await page.evaluate(
        """() => document.getElementById('btn-export').closest('.export-group')
            === document.getElementById('export-format').closest('.export-group')"""
    )
    assert same_group

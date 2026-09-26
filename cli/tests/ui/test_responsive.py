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
# alerts' form rows and tables, settings' form rows), plus the Groups card
# row: `.fp-group-card` (web/components.css) packed a badge, a name, six
# avatars and two buttons onto one non-wrapping line and grew the page past
# the viewport. Fixed in P2-E5-W3-S1-T2 by letting the card and its avatar
# strip wrap, and covered here rather than in a second overflow test.
@pytest.mark.parametrize("surface", ("dashboard", "alerts", "settings", "groups"))
async def test_no_horizontal_overflow_at_phone_width(page, base_url, surface):
    """No element pushes the page wider than the viewport at 375px.

    Caught the rules/delivery-log tables (7 and 6 columns) and the
    Settings/Alerts .setting-row inputs (190px min-width) both growing the
    page past its own width instead of scrolling within their own box.
    """
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")
    if surface in ("alerts", "groups"):
        await _open_tab(page, surface)
        if surface == "groups":
            # Not ".fp-group-card, .fp-empty-state": places.html's own empty
            # state shares that class (see test_groups_dialog.py's
            # _open_groups_tab()); this marker is set once groups.js is wired.
            await page.wait_for_selector('[data-fp-ready="groups"]')
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


async def test_map_top_within_first_viewport_at_phone_width(page, base_url):
    """UAT U26: the map used to sit entirely below a full 812px screen of
    stacked cards and wrapped filters. The compact 2-column cards and
    tighter filter spacing (responsive.css) bring its top edge back inside
    the first screen instead of a full scroll down."""
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")

    box = await page.locator("#map").bounding_box()
    assert box is not None
    assert box["y"] < PHONE_HEIGHT * 0.75, f"#map top at y={box['y']}, not within the first screen"


async def test_group_label_stays_with_its_select_at_phone_width(page, base_url):
    """UAT U26: "Group:" used to wrap onto its own line, separated from the
    select it labels, when .controls wrapped at phone width."""
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")

    label_box = await page.locator('label[for="fp-group-select"]').bounding_box()
    select_box = await page.locator("#fp-group-select").bounding_box()
    assert label_box is not None and select_box is not None
    assert abs(label_box["y"] - select_box["y"]) < 10, (
        "Group: label not on the same row as its select"
    )


async def test_day_label_stays_with_its_date_input_at_phone_width(page, base_url):
    """UAT2 U26 (leftover from U26's own fix): "Day" wrapped onto the Group
    row while its own #day-picker input dropped to a line by itself, since
    only the Group label+select were grouped as one flex item."""
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")

    label_box = await page.locator('label[for="day-picker"]').bounding_box()
    input_box = await page.locator("#day-picker").bounding_box()
    assert label_box is not None and input_box is not None
    assert abs(label_box["y"] - input_box["y"]) < 10, (
        "Day label not on the same row as its date input"
    )


async def test_more_menu_closes_on_escape_and_returns_focus(page, base_url):
    """UAT3 N22: the More menu stayed open after Escape, with no handler for
    the key at all. Closing now also hands focus back to #btn-more, the
    element that opened it."""
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")

    await page.click("#btn-more")
    await page.wait_for_selector("#fp-more-menu:not(.hidden)")
    await page.keyboard.press("Escape")
    # Not wait_for_selector("#fp-more-menu.hidden", the default "visible"
    # state): a hidden menu is never visible by definition, so that would
    # never resolve (same reasoning as test_settings_errors.py's _open_settings).
    await page.wait_for_function(
        "document.getElementById('fp-more-menu').classList.contains('hidden')"
    )
    assert await page.get_attribute("#btn-more", "aria-expanded") == "false"
    focused = await page.evaluate("document.activeElement.id")
    assert focused == "btn-more"


async def test_more_menu_closes_on_outside_click_and_returns_focus(page, base_url):
    """UAT3 N22: a tap outside the open menu used to do nothing."""
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")

    await page.click("#btn-more")
    await page.wait_for_selector("#fp-more-menu:not(.hidden)")
    await page.mouse.click(10, 10)  # outside the menu and the More button
    await page.wait_for_function(
        "document.getElementById('fp-more-menu').classList.contains('hidden')"
    )
    assert await page.get_attribute("#btn-more", "aria-expanded") == "false"
    focused = await page.evaluate("document.activeElement.id")
    assert focused == "btn-more"


async def test_tabbar_icons_are_svg_not_emoji(page, base_url):
    """UAT2 U26: the phone-tier tab bar used emoji glyphs, which render
    inconsistently across platforms and fonts. Each icon is now a sprite
    <use> reference; the visible text label (never aria-hidden) still gives
    each button its accessible name."""
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")

    buttons = page.locator(".fp-tabbar button")
    assert await buttons.count() == 4
    for i in range(await buttons.count()):
        btn = buttons.nth(i)
        assert await btn.locator("svg.fp-tabbar-icon use").count() == 1
        text = await btn.inner_text()
        assert text.strip(), "tab button has no visible accessible-name text"
        for emoji in ("\U0001f3e0", "\U0001f4cd", "\U0001f465", "\U0001f514"):
            assert emoji not in text


async def test_more_button_label_is_vertically_centered(page, base_url):
    """UAT4 N42: the forced 44px touch-target height (responsive.css) left
    "More"'s single-line label pinned to the top of the button, with the
    extra height as dead space below it, instead of centred in the middle of
    the tall box."""
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#btn-more", state="visible")

    boxes = await page.evaluate(
        """() => {
            const btn = document.getElementById('btn-more');
            const btnRect = btn.getBoundingClientRect();
            const textNode = [...btn.childNodes].find(
                (n) => n.nodeType === Node.TEXT_NODE && n.textContent.trim()
            );
            const range = document.createRange();
            range.selectNodeContents(textNode);
            const textRect = range.getBoundingClientRect();
            return {
                btnTop: btnRect.top, btnHeight: btnRect.height,
                textTop: textRect.top, textHeight: textRect.height,
            };
        }"""
    )
    btn_center = boxes["btnTop"] + boxes["btnHeight"] / 2
    text_center = boxes["textTop"] + boxes["textHeight"] / 2
    assert abs(btn_center - text_center) <= 3, (
        f"'More' label not vertically centred: button center {btn_center}, "
        f"label center {text_center}"
    )
    assert boxes["btnHeight"] >= 44, "the 44px touch target itself must not shrink"

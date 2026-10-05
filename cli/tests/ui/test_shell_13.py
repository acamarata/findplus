"""Dashboard 1.3 shell: app bar, Add menu, tab row, panel memory, button system.

Purpose    : Pin the shell the Latest, People and Activity builders mount into:
             five tabs in order, Latest by default, a remembered tab, hash deep
             links (`#/groups` is People), the app bar's icon+label buttons and
             Add menu, "Fit to latest" inside the map, the compact status strip
             and the button helper's contract.
Inputs     : live_server and the seeded ui_db (conftest.py).
Outputs    : Assertions only.
Constraints: Headless Chromium against the throwaway server; nothing reaches a
             real account or the owner's state directory.
"""

# ruff: noqa: E501  (inline JS snippets)
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

TABS = ["latest", "people", "activity", "places", "alerts"]


async def _boot(page, base_url, path="/", width=1280, height=800):
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(base_url + path)
    await page.wait_for_selector("#app-shell[data-fp-ready]", timeout=20000)


async def _active(page):
    return await page.evaluate("document.querySelector('.fp-tabs .fp-tab.active').dataset.tab")


async def test_tab_row_is_five_tabs_with_latest_first_and_active(page, base_url):
    await _boot(page, base_url)
    order = await page.eval_on_selector_all(
        ".fp-tabs .fp-tab", "els => els.map(e => e.dataset.tab)"
    )
    assert order == TABS
    assert await _active(page) == "latest"
    assert await page.is_visible("#tab-latest")
    assert await page.is_hidden("#tab-activity")


async def test_the_last_tab_is_remembered(page, base_url):
    await _boot(page, base_url)
    await page.click('.fp-tabs [data-tab="activity"]')
    await page.wait_for_selector("#tab-activity:not([hidden])")
    assert await page.evaluate("localStorage.getItem('findplus.panelTab')") == "activity"
    await page.reload()
    await page.wait_for_selector("#app-shell[data-fp-ready]", timeout=20000)
    assert await _active(page) == "activity"
    await page.evaluate("localStorage.removeItem('findplus.panelTab')")


@pytest.mark.parametrize(
    ("hash_", "tab"),
    (
        ("#/latest", "latest"),
        ("#/people", "people"),
        ("#/groups", "people"),
        ("#/activity", "activity"),
        ("#/places", "places"),
        ("#/alerts", "alerts"),
    ),
)
async def test_hash_routes_select_a_tab(page, base_url, hash_, tab):
    await _boot(page, base_url, "/" + hash_)
    assert await _active(page) == tab
    await page.evaluate("localStorage.removeItem('findplus.panelTab')")


async def test_hash_change_switches_tab_after_boot(page, base_url):
    await _boot(page, base_url)
    await page.evaluate("window.location.hash = '#/people'")
    await page.wait_for_selector("#tab-people:not([hidden])")
    assert await _active(page) == "people"
    await page.evaluate("localStorage.removeItem('findplus.panelTab')")


async def test_latest_keeps_day_story_and_every_sighting_switch(page, base_url):
    await _boot(page, base_url)
    assert await page.is_visible("#view-switch")
    await page.wait_for_selector("#tracks > *", state="attached")


async def test_activity_shows_every_sighting_without_the_switch(page, base_url):
    await _boot(page, base_url)
    await page.click('.fp-tabs [data-tab="activity"]')
    await page.wait_for_selector("#tab-activity:not([hidden])")
    await page.wait_for_selector("#tab-activity #tracks .track-block", state="attached")
    assert await page.is_hidden("#view-switch")
    assert await page.is_hidden("#story")
    # Back on Latest the one shared body returns to its own panel.
    await page.click('.fp-tabs [data-tab="latest"]')
    await page.wait_for_selector("#tab-latest #tracks", state="attached")
    assert await page.is_visible("#view-switch")
    await page.evaluate("localStorage.removeItem('findplus.panelTab')")


async def test_people_tab_still_shows_groups_content(page, base_url):
    await _boot(page, base_url)
    await page.click('.fp-tabs [data-tab="people"]')
    await page.wait_for_selector("#tab-people #fp-groups-list", state="visible")
    assert await page.is_visible("#fp-add-group-btn")
    await page.evaluate("localStorage.removeItem('findplus.panelTab')")


async def test_app_bar_buttons_are_icon_and_label(page, base_url):
    await _boot(page, base_url)
    for btn_id in ("btn-poll", "btn-add", "btn-devices", "btn-settings"):
        btn = page.locator(f"#{btn_id}")
        assert "fp-btn" in (await btn.get_attribute("class"))
        assert await btn.locator("svg.fp-btn-icon[aria-hidden='true']").count() == 1
        assert (await btn.inner_text()).strip()
    assert "fp-btn--primary" in (await page.get_attribute("#btn-add", "class"))


async def test_fit_to_latest_lives_in_the_map(page, base_url):
    await _boot(page, base_url)
    inside = await page.evaluate(
        "document.getElementById('map').contains(document.getElementById('btn-latest'))"
    )
    assert inside
    assert (await page.inner_text("#btn-latest")).strip() == "Fit to latest"
    assert await page.evaluate("!document.querySelector('.topbar #btn-latest')")


async def test_add_menu_opens_place_person_and_group_flows(page, base_url):
    await _boot(page, base_url)
    await page.click("#btn-add")
    await page.wait_for_selector("#fp-add-menu:not(.hidden)")
    assert await page.get_attribute("#btn-add", "aria-expanded") == "true"
    labels = await page.eval_on_selector_all(
        "#fp-add-menu [role=menuitem]", "els => els.map(e => e.innerText.trim())"
    )
    assert labels == ["Place", "Person", "Group"]

    await page.click("#fp-add-place")
    await page.wait_for_selector("#fp-place-dialog[open]")
    await page.keyboard.press("Escape")

    await page.click("#btn-add")
    await page.click("#fp-add-group")
    await page.wait_for_selector("#fp-group-dialog[open]")
    await page.keyboard.press("Escape")

    await page.click("#btn-add")
    await page.click("#fp-add-person")
    await page.wait_for_selector("#fp-person-dialog[open]")
    assert "Add a person" in await page.inner_text("#fp-person-dialog-title")
    await page.keyboard.press("Escape")


async def test_add_menu_closes_on_escape_and_returns_focus(page, base_url):
    await _boot(page, base_url)
    await page.click("#btn-add")
    await page.wait_for_selector("#fp-add-menu:not(.hidden)")
    await page.keyboard.press("Escape")
    await page.wait_for_selector("#fp-add-menu.hidden", state="attached")
    assert await page.evaluate("document.activeElement.id") == "btn-add"


async def test_status_cards_are_one_compact_row_at_desktop_width(page, base_url):
    await _boot(page, base_url, width=1400, height=900)
    tops = await page.eval_on_selector_all(
        "#cards .card", "els => els.map(e => Math.round(e.getBoundingClientRect().top))"
    )
    assert len(tops) == 4 and len(set(tops)) == 1
    assert await page.is_visible("#cards-help summary")


async def test_button_helper_contract(page, base_url):
    await _boot(page, base_url)
    out = await page.evaluate(
        """async () => {
            const m = await import('/static/app/components/button.js');
            const full = m.button({ label: 'Delete', icon: 'trash-2', variant: 'danger', size: 'sm', title: 'Remove it' });
            const only = m.button({ label: 'Edit', icon: 'pencil', iconOnly: true });
            return {
              cls: full.className, type: full.type, title: full.title,
              hidden: full.querySelector('svg').getAttribute('aria-hidden'),
              onlyCls: only.className, aria: only.getAttribute('aria-label'), onlyText: only.textContent,
            };
        }"""
    )
    assert out["cls"] == "fp-btn fp-btn--danger fp-btn--sm"
    assert out["type"] == "button" and out["title"] == "Remove it" and out["hidden"] == "true"
    assert "fp-btn--icon" in out["onlyCls"] and out["aria"] == "Edit" and out["onlyText"] == ""


async def test_places_tab_buttons_use_the_button_system(page, base_url):
    await _boot(page, base_url)
    await page.click('.fp-tabs [data-tab="places"]')
    await page.wait_for_selector("#tab-places:not([hidden])")
    assert "fp-btn--primary" in (await page.get_attribute("#fp-add-place-btn", "class"))
    await page.evaluate("localStorage.removeItem('findplus.panelTab')")


async def test_dom_order_is_tabs_panel_filters_map(page, base_url):
    await _boot(page, base_url)
    order = await page.evaluate(
        """() => {
            const pos = (sel) => {
                const el = document.querySelector(sel);
                return [...document.querySelectorAll('*')].indexOf(el);
            };
            return [pos('.fp-topnav'), pos('#timeline-pane'), pos('.status-region'), pos('#map-pane')];
        }"""
    )
    assert order == sorted(order) and len(set(order)) == 4


async def test_a_deep_link_does_not_overwrite_the_remembered_tab(page, base_url):
    await _boot(page, base_url)
    await page.click('.fp-tabs [data-tab="activity"]')
    await page.goto(base_url + "/#/places")
    await page.reload()
    await page.wait_for_selector("#app-shell[data-fp-ready]", timeout=20000)
    assert await _active(page) == "places"
    assert await page.evaluate("localStorage.getItem('findplus.panelTab')") == "activity"
    await page.evaluate("localStorage.removeItem('findplus.panelTab')")


async def test_desktop_panel_is_its_own_sticky_column(page, base_url):
    await _boot(page, base_url, width=1400, height=900)
    box = await page.evaluate(
        """() => {
            const p = document.getElementById('timeline-pane');
            const m = document.getElementById('map-pane');
            return {
                panel: getComputedStyle(p).position, map: getComputedStyle(m).position,
                panelLeft: p.getBoundingClientRect().left, mapLeft: m.getBoundingClientRect().left,
            };
        }"""
    )
    assert box["panel"] == "sticky" and box["map"] == "sticky"
    assert box["panelLeft"] > box["mapLeft"]


async def test_marker_popup_offers_show_only_this(page, base_url):
    await _boot(page, base_url)
    await page.wait_for_selector(".marker-num-glyph", state="attached")
    await page.evaluate(
        """() => {
            window.__focused = null;
            window.addEventListener('findplus:focus-tracker', (e) => { window.__focused = e.detail.device_id; });
        }"""
    )
    await page.locator(".leaflet-marker-icon").first.click(force=True)
    await page.click(".fp-popup-focus")
    assert await page.evaluate("window.__focused") is not None

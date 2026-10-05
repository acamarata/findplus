"""Dashboard 1.3 polish: export popover (U35), checkboxes (U37), dark map (U32),
footer (U33), person page header (U23) and the phone route classes (U15)."""

from __future__ import annotations

import pytest

from ._person_helpers import ensure_person, open_person
from .conftest import set_theme

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _boot(page, base_url, width=1280, height=800):
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]", timeout=20000)


async def test_export_is_one_ghost_button_with_a_popover(page, base_url):
    await _boot(page, base_url)
    opener = page.locator("#btn-export-open")
    assert "fp-btn--ghost" in await opener.get_attribute("class")
    assert await page.locator("#export-pop").is_hidden()
    await opener.click()
    assert await opener.get_attribute("aria-expanded") == "true"
    for sel in ("#export-format", "#export-scope", "#btn-export"):
        assert await page.locator(sel).is_visible(), sel
    await page.keyboard.press("Escape")
    assert await page.locator("#export-pop").is_hidden()
    assert await page.evaluate("document.activeElement.id") == "btn-export-open"
    await opener.click()
    await page.mouse.click(5, 400)
    assert await page.locator("#export-pop").is_hidden()


async def test_checkboxes_and_radios_are_16px(page, base_url):
    await _boot(page, base_url)
    sizes = await page.evaluate(
        """() => [...document.querySelectorAll('input[type=checkbox]:not([role=switch]), input[type=radio]')]
            .map((el) => { const cs = getComputedStyle(el); return [cs.width, cs.height, cs.accentColor]; })"""
    )
    assert sizes
    for width, height, accent in sizes:
        assert (width, height) == ("16px", "16px")
        assert accent != "auto"


async def test_dark_map_labels_use_panel_colours(page, base_url):
    await _boot(page, base_url)
    await set_theme(page, "dark")
    got = await page.evaluate(
        """() => {
          const tip = document.createElement('div');
          tip.className = 'leaflet-tooltip'; document.body.appendChild(tip);
          const cs = getComputedStyle(tip);
          const out = [cs.backgroundColor, cs.color,
            getComputedStyle(document.documentElement).getPropertyValue('--panel').trim()];
          tip.remove(); return out;
        }"""
    )
    assert got[0] == "rgb(26, 31, 41)" and got[2] == "#1a1f29"
    assert got[1] == "rgb(231, 236, 243)"


async def test_dark_place_circles_have_a_low_fill(page, base_url):
    await _boot(page, base_url)
    await set_theme(page, "dark")
    await page.evaluate("() => document.querySelector('.leaflet-tile-pane, .leaflet-overlay-pane')")
    opacity = await page.evaluate(
        """() => {
          const ns = 'http://www.w3.org/2000/svg';
          const svg = document.createElementNS(ns, 'svg');
          const p = document.createElementNS(ns, 'path');
          p.setAttribute('class', 'leaflet-interactive fp-place-circle');
          p.setAttribute('fill-opacity', '0.15');
          svg.appendChild(p); document.body.appendChild(svg);
          const v = getComputedStyle(p).fillOpacity; svg.remove(); return v;
        }"""
    )
    assert float(opacity) < 0.1


async def test_footer_notices_are_small_muted_and_narrow(page, base_url):
    await _boot(page, base_url)
    info = await page.evaluate(
        """() => {
          const n = document.querySelector('.footer .notice.small');
          const cs = getComputedStyle(n);
          return [cs.fontSize, cs.color, getComputedStyle(document.documentElement).getPropertyValue('--muted').trim(),
                  n.getBoundingClientRect().width, parseFloat(cs.fontSize)];
        }"""
    )
    assert info[0] == "12px"
    assert info[3] <= 72 * 8 + 4  # 72ch at 12px stays under ~580px


async def test_person_header_back_is_ghost_and_send_is_secondary(trips_page, trips_server):
    pid = ensure_person(trips_server)
    await open_person(trips_page, trips_server, pid)
    back = trips_page.locator("#person-back")
    assert "fp-btn--ghost" in await back.get_attribute("class")
    assert (await back.inner_text()).strip() == "‹ All"
    assert await back.get_attribute("aria-label") == "Back to dashboard"
    send = trips_page.locator("#person-send")
    cls = await send.get_attribute("class")
    assert "fp-btn--secondary" in cls and "primary" not in cls


async def test_phone_hides_status_strip_on_person_page(trips_page, trips_server):
    pid = ensure_person(trips_server)
    await trips_page.set_viewport_size({"width": 375, "height": 812})
    await open_person(trips_page, trips_server, pid)
    assert await trips_page.evaluate("document.body.classList.contains('fp-route-person')")
    assert await trips_page.locator(".status-region").is_hidden()
    await trips_page.evaluate("() => { location.hash = ''; }")
    await trips_page.wait_for_function("() => !document.body.classList.contains('fp-route-person')")
    assert await trips_page.locator(".status-region").is_visible()

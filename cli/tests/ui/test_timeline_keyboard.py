"""Timeline rows are keyboard selectable, and the map adds no nameless Tab stops.

UAT #6: rows were click-only. They are now one roving-tabindex group (one Tab
stop, arrows move, Enter or Space selects). The map's own shapes must never be
a Tab stop without an accessible name: a keyboard user reaches the timeline
instead (map.js, "keyboard: false").
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from ._latest_helpers import PARK_BODY

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _activity_body(page):
    """The all-trackers day body is no pane of its own in 1.3: show the legacy body in Latest."""
    await page.add_init_script(PARK_BODY)


async def _boot(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#tracks .tl-item")


async def test_rows_form_one_roving_tab_stop(page, base_url):
    await _boot(page, base_url)
    await page.wait_for_selector(".tl-item")
    stops = await page.evaluate(
        "() => [...document.querySelectorAll('.tl-item')].filter((e) => e.tabIndex === 0).length"
    )
    assert stops == 1


async def test_arrows_move_and_enter_selects(page, base_url):
    await _boot(page, base_url)
    first = page.locator(".tl-item").first
    await first.focus()
    await page.keyboard.press("ArrowDown")
    second = page.locator(".tl-item").nth(1)
    assert await second.evaluate("(e) => e === document.activeElement")
    assert await second.get_attribute("tabindex") == "0"
    assert await first.get_attribute("tabindex") == "-1"
    await page.keyboard.press("Enter")
    assert "selected" in (await second.get_attribute("class"))
    await page.keyboard.press("ArrowUp")
    await page.keyboard.press(" ")
    assert "selected" in (await first.get_attribute("class"))
    assert "selected" not in (await second.get_attribute("class"))


async def test_map_has_no_nameless_tab_stop(page, base_url):
    made = await page.request.post(
        base_url + "/api/places",
        data={"name": "Keys P", "latitude": 40.0, "longitude": -74.0, "radius_meters": 150},
    )
    place_id = (await made.json())["id"]
    try:
        await _boot(page, base_url)
        await page.click('button[data-tab="places"]')
        nameless = await page.evaluate(
            """() => [...document.querySelectorAll('#map *')]
                .filter((e) => e.tabIndex >= 0 && e.matches('path, svg, [role=img]')
                  && !(e.getAttribute('aria-label') || '').trim())
                .map((e) => e.tagName)"""
        )
        assert nameless == []
    finally:
        await page.request.delete(f"{base_url}/api/places/{place_id}")

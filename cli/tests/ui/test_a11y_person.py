"""axe-core scan of the people surfaces: person page, suggestions, notices, settings, place dialog."""

from __future__ import annotations

import pytest
from axe_playwright_python.async_playwright import Axe

from ._person_helpers import ensure_person, open_person
from ._suggest_helpers import payload
from .conftest import set_theme
from .test_a11y import AXE_OPTIONS, BLOCKING, _describe
from .test_left_behind_chips import episode

pytestmark = pytest.mark.asyncio(loop_scope="session")
THEMES = ("dark", "light")
WIDTHS = (1280, 375)


async def _scan(page, name: str, theme: str, width: int) -> None:
    await set_theme(page, theme)
    results = await Axe().run(page, options=AXE_OPTIONS)
    found = [v for v in results.response["violations"] if v.get("impact") in BLOCKING]
    assert not found, "\n".join(_describe(v, name, theme, width) for v in found)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", WIDTHS)
async def test_person_page(trips_page, trips_server, theme, width):
    pid = ensure_person(trips_server)
    await trips_page.set_viewport_size({"width": width, "height": 900})
    await open_person(trips_page, trips_server, pid)
    await trips_page.get_by_role("button", name="Edit Sam").first.click()
    await _scan(trips_page, "person", theme, width)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", WIDTHS)
async def test_suggestions_and_notices(trips_page, trips_server, theme, width):
    pid = ensure_person(trips_server)

    async def sugg(route):
        await route.fulfill(json=payload())

    async def left(route):
        await route.fulfill(json=[episode(1, "left_behind")])

    await trips_page.route("**/api/people/suggestions", sugg)
    await trips_page.route(f"**/api/people/{pid}/left-behind", left)
    await trips_page.set_viewport_size({"width": width, "height": 900})
    await trips_page.goto(trips_server["base"] + "/")
    await trips_page.wait_for_selector("#fp-left-behind:not([hidden])")
    await trips_page.wait_for_selector("#fp-people-banner:not([hidden])")
    await _scan(trips_page, "dashboard-notices", theme, width)
    tab = '.fp-tabbar [data-tabbar-tab="groups"]' if width < 600 else '.fp-tabs [data-tab="groups"]'
    await trips_page.click(tab)
    await trips_page.wait_for_selector("#tab-groups .ps-card")
    await _scan(trips_page, "suggestions", theme, width)


@pytest.mark.parametrize("theme", THEMES)
async def test_place_dialog_and_settings(trips_page, trips_server, theme):
    ensure_person(trips_server)
    p = trips_page
    await p.goto(trips_server["base"] + "/")
    await p.wait_for_selector("#app-shell[data-fp-ready]")
    await p.click('.fp-tabs [data-tab="places"]')
    await p.click("#fp-add-place-btn")
    await p.wait_for_selector("#fp-place-notify-line:not(:empty)")
    await _scan(p, "place-dialog", theme, 1280)
    await p.keyboard.press("Escape")
    await p.click("#btn-settings")
    await p.wait_for_selector("#person-backup-line:not(:empty)")
    await _scan(p, "settings", theme, 1280)

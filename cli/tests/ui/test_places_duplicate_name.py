"""Places tab: the duplicate-name 409's dialog message (UAT5 N48).

Split out of test_places.py (T1, 2026-09-23, PRI rule-7 300-line file cap):
this file was at the cap and this one test pushed it over.

Seed data (cli/tests/ui/conftest.py): place "Home" at (41.1, -80.1) r=200m,
which is what the save here is expected to collide with.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_dashboard(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")


async def test_add_place_duplicate_name_shows_catalog_sentence(page, base_url):
    """N48: the 409 for a duplicate name used to reach the dialog as the
    server's raw text ("place name 'Home' already exists"), Python repr
    quoting and all. It now reads as the catalog sentence."""
    await _open_dashboard(page, base_url)
    await page.click('button[data-tab="places"]')
    await page.click("#fp-add-place-btn")
    dialog = page.locator("#fp-place-dialog")
    await dialog.wait_for(state="visible")

    await dialog.locator("#fp-place-name").fill("Home")
    await dialog.get_by_text("Save", exact=True).click()

    error = page.locator("#fp-place-dialog-error")
    await error.wait_for(state="visible")
    assert await error.inner_text() == "A place named Home already exists."
    assert "'" not in await error.inner_text()
    assert await dialog.get_attribute("open") is not None

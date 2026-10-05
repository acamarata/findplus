"""The Add place dialog says where the place will go and stops at 64 characters.

UAT #8: the name box took 80 characters while the server accepts 1-64, so 65-80
ended in a server error. UAT #9: a place saved with only a name landed at the map
centre without a word; the dialog now shows the location line from the start.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_add(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")
    await page.click('button[data-tab="places"]')
    await page.click("#fp-add-place-btn")
    await page.wait_for_selector("#fp-place-dialog[open]")


async def test_name_input_matches_the_server_limit(page, base_url):
    await _open_add(page, base_url)
    await page.fill("#fp-place-name", "x" * 80)
    assert len(await page.input_value("#fp-place-name")) == 64


async def test_dialog_says_it_will_use_the_map_centre(page, base_url):
    await _open_add(page, base_url)
    line = await page.locator("#fp-place-where").inner_text()
    assert line.startswith("Location: ") and "the centre of the map" in line
    assert "," in line


async def test_line_follows_a_tracker_pick(page, base_url):
    await _open_add(page, base_url)
    await page.select_option("#fp-place-tracker-select", "TAG-HOME")
    await page.click("#fp-place-use-tracker-btn")
    await page.wait_for_function(
        "() => document.getElementById('fp-place-where').textContent.includes('41.1000')"
    )
    assert "41.1000" in await page.locator("#fp-place-where").inner_text()

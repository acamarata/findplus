"""Two trackers with one name are told apart in every picker (UAT #7).

Roster (`_roster17.py`): R17-00 and R17-01 are both "Ali Pixel 8a" and tracked,
R17-02 and R17-10 are both "Sam Shoes Red" (only R17-02 tracked), and the rest
have unique names. A unique name must stay exactly as it was.
"""

from __future__ import annotations

import pytest

from ._roster17 import roster17

pytestmark = pytest.mark.asyncio(loop_scope="session")

TWINS = ["Ali Pixel 8a (7-00)", "Ali Pixel 8a (7-01)"]


async def _boot(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")


async def _texts(page, selector):
    return [t.strip() for t in await page.locator(f"{selector} option").all_inner_texts()]


async def test_show_filter_tells_the_twins_apart(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _boot(page, base_url)
        texts = await _texts(page, "#device-filter")
        twins = [t for t in texts if t.startswith("Ali Pixel 8a")]
        assert [t.split(" (Find Hub)")[0] for t in twins] == TWINS
        # A unique name is untouched: no id tail before the provider.
        assert any(t.startswith("Tag 5 (Find Hub)") for t in texts)


async def test_rule_device_select_tells_the_twins_apart(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _boot(page, base_url)
        await page.click('button[data-tab="alerts"]')
        await page.wait_for_selector("#fp-add-rule-btn")
        await page.click("#fp-add-rule-btn")
        await page.wait_for_selector("#fp-rule-device option[value='R17-00']", state="attached")
        texts = await _texts(page, "#fp-rule-device")
        assert [t for t in texts if t.startswith("Ali Pixel 8a")] == TWINS
        # The untracked twin of a tracked name is told apart too.
        assert sum(t.startswith("Sam Shoes Red (") for t in texts) == 2


async def test_place_dialog_tracker_select_tells_the_twins_apart(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        await _boot(page, base_url)
        await page.click('button[data-tab="places"]')
        await page.click("#fp-add-place-btn")
        await page.wait_for_selector(
            "#fp-place-tracker-select option[value='R17-00']", state="attached"
        )
        texts = await _texts(page, "#fp-place-tracker-select")
        assert [t for t in texts if t.startswith("Ali Pixel 8a")] == TWINS

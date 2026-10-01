"""Delete history answers inside the Settings dialog (UAT #16).

"Delete older than..." with no date did nothing: its message went to the page
banner, behind the dialog. It now shows under the buttons, where the click was.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_settings(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")
    await page.click("#btn-settings")
    await page.wait_for_selector("#settings-modal[data-loaded='true']")


async def test_empty_date_says_to_pick_one(page, base_url):
    await _open_settings(page, base_url)
    await page.fill("#delete-before-date", "")
    await page.click("#btn-delete-before")
    result = page.locator("#delete-result")
    await result.wait_for(state="visible")
    assert await result.inner_text() == "Pick a date first."
    assert await page.locator("#fp-confirm-dialog[open]").count() == 0


async def test_nothing_older_is_reported_in_the_dialog(page, base_url):
    await _open_settings(page, base_url)
    await page.fill("#delete-before-date", "2000-01-01")
    await page.click("#btn-delete-before")
    await page.wait_for_function(
        "() => document.getElementById('delete-result').textContent.includes('Nothing is older')"
    )

"""A dead API reads as a sentence with a Retry, never the browser's own text.

UAT #14: "Could not load 2026-10-01: Failed to fetch" and a bare "Failed to
fetch" in the place dialog named no cause and offered no way forward. api.js now
turns a network failure into one plain sentence, and the banners carry Retry.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _activity_body(page):
    """The all-trackers day body lives in the Activity tab now (dashboard 1.3)."""
    await page.add_init_script("localStorage.setItem('findplus.panelTab','activity')")


SENTENCE = "Find+ is not answering. Check that it is still running, then try again."


async def _abort(route):
    await route.abort("connectionrefused")


async def test_timeline_banner_and_pane_use_the_plain_sentence_and_retry(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#tracks .track-block")
    await page.route("**/api/timeline*", _abort)
    await page.select_option("#device-filter", "TAG-AWAY")
    banner = page.locator("#alert")
    await banner.get_by_role("button", name="Retry").wait_for()
    text = await banner.inner_text()
    assert SENTENCE in text and "Failed to fetch" not in text
    assert SENTENCE in await page.locator("#tracks [data-pane-error]").inner_text()
    await page.unroute("**/api/timeline*", _abort)
    await banner.get_by_role("button", name="Retry").click()
    await page.wait_for_selector("#tracks .track-block")
    await page.select_option("#device-filter", "")


async def test_place_dialog_save_failure_is_the_plain_sentence(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")
    await page.click('button[data-tab="places"]')
    await page.click("#fp-add-place-btn")
    await page.wait_for_selector("#fp-place-dialog[open]")
    await page.fill("#fp-place-name", "Offline probe")
    await page.route("**/api/places", _abort)
    await page.locator("#fp-place-dialog").get_by_role("button", name="Save").click()
    await page.wait_for_function(
        "() => document.getElementById('fp-place-dialog-error').textContent.length > 0"
    )
    assert await page.locator("#fp-place-dialog-error").inner_text() == SENTENCE

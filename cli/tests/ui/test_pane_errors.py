"""A failed load gives the timeline and Groups panes an error state with Retry.

UAT #1/#2: a failed refresh left the previous device's timeline under the new
selection, and a 500 from /api/groups left the Groups tab with no message at
all. Each pane now shows its own error, clears what it showed before, and offers
a Retry that recovers once the API answers again.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _fail(route):
    await route.fulfill(status=500, json={"detail": "boom"})


async def test_failed_timeline_load_clears_the_old_rows_and_retries(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#tracks .track-block")
    await page.route("**/api/timeline*", _fail)
    await page.select_option("#device-filter", "TAG-AWAY")
    pane = page.locator("#tracks [data-pane-error]")
    await pane.wait_for()
    assert await page.locator("#tracks .track-block").count() == 0
    assert "boom" in await pane.inner_text()
    await page.unroute("**/api/timeline*", _fail)
    await pane.get_by_role("button", name="Retry").click()
    await page.wait_for_selector("#tracks .track-block")
    assert await page.locator("#tracks [data-pane-error]").count() == 0
    await page.select_option("#device-filter", "")


async def test_background_failure_keeps_the_same_selection_rows(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#tracks .track-block")
    await page.route("**/api/timeline*", _fail)
    await page.evaluate("document.getElementById('btn-today').click()")
    await page.wait_for_selector("#alert:not(.hidden)")
    assert await page.locator("#tracks [data-pane-error]").count() == 0
    await page.unroute("**/api/timeline*", _fail)


async def test_groups_tab_shows_error_and_retry(page, base_url):
    await page.route("**/api/groups", _fail)
    await page.goto(base_url + "/")
    await page.click('button[data-tab="people"]')
    pane = page.locator("#fp-groups-list [data-pane-error]")
    await pane.wait_for()
    assert "boom" in await pane.inner_text()
    assert await page.locator("#fp-groups-tab-hint").is_hidden()
    await page.unroute("**/api/groups", _fail)
    await pane.get_by_role("button", name="Retry").click()
    await page.wait_for_selector("#fp-groups-list .fp-group-card")
    assert await page.locator("#fp-groups-list [data-pane-error]").count() == 0


async def test_presence_failure_clears_the_old_verdict(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#fp-group-select")
    await page.select_option("#fp-group-select", label="Family")
    await page.click('button[data-tab="people"]')
    await page.wait_for_selector("#fp-presence-panel .fp-verdict")
    await page.route("**/api/groups/*/presence*", _fail)
    await page.click('button[data-tab="people"]')
    await page.select_option("#fp-group-select", "")
    await page.select_option("#fp-group-select", label="Family")
    pane = page.locator("#fp-presence-panel [data-pane-error]")
    await pane.wait_for()
    assert await page.locator("#fp-presence-panel .fp-verdict").count() == 0
    await page.unroute("**/api/groups/*/presence*", _fail)
    await pane.get_by_role("button", name="Retry").click()
    await page.wait_for_selector("#fp-presence-panel .fp-verdict")

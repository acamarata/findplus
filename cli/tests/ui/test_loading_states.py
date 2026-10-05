"""Slow loads show a loading state instead of a blank or a wrong empty state.

UAT #13: while /api/places was slow the Places tab said "Use Add place to create
a geofence" (wrong: nothing is known yet), and the dashboard pane was blank while
the timeline loaded. A failed places load now gets its own error with Retry too.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_places_tab_loads_before_it_claims_there_are_none(page, base_url):
    release = asyncio.Event()

    async def slow_empty(route):
        await release.wait()
        await route.fulfill(json=[])

    await page.route("**/api/places", slow_empty)
    await page.goto(base_url + "/")
    await page.click('button[data-tab="places"]')
    loading = page.locator("#fp-places-list [role=status]")
    await loading.wait_for()
    assert await page.locator("#fp-places-tab-hint").is_hidden()
    release.set()
    await page.locator("#fp-places-tab-hint").wait_for(state="visible")
    assert await loading.count() == 0


async def test_places_failure_has_an_error_and_retry(page, base_url):
    async def fail(route):
        await route.fulfill(status=500, json={"detail": "places broke"})

    await page.route("**/api/places", fail)
    await page.goto(base_url + "/")
    await page.click('button[data-tab="places"]')
    pane = page.locator("#fp-places-list [data-pane-error]")
    await pane.wait_for()
    assert "Find+ could not load your places. Try again." in await pane.inner_text()
    await pane.locator("summary").click()
    assert "places broke" in await pane.inner_text()
    assert await page.locator("#fp-places-tab-hint").is_hidden()
    await page.unroute("**/api/places", fail)
    await pane.get_by_role("button", name="Retry").click()
    await page.wait_for_selector("#fp-places-list .fp-place-card")


async def test_timeline_pane_shows_loading_for_a_slow_new_selection(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#tracks .track-block")
    release = asyncio.Event()

    async def slow(route):
        await release.wait()
        await route.continue_()

    await page.route("**/api/timeline*", slow)
    await page.select_option("#device-filter", "TAG-AWAY")
    await page.wait_for_selector("#tracks [role=status]")
    assert await page.locator("#tracks .track-block").count() == 0
    release.set()
    await page.wait_for_selector("#tracks .track-block")
    await page.select_option("#device-filter", "")

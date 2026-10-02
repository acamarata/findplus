"""The "N places have no arrival alerts. Notify me" banner: a preview first, then the write."""

from __future__ import annotations

import json
import re

import pytest

from ._notify_helpers import WEBHOOK, channels
from ._person_helpers import ALERTS_LATENCY

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_places(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]")
    await page.click('button[data-tab="places"]')
    await page.wait_for_selector("#fp-places-backfill:not([hidden])")


async def _drop_default_rules(page, base_url):
    for rule in await (await page.request.get(base_url + "/api/alerts/rules")).json():
        if rule["all_people"]:
            await page.request.delete(f"{base_url}/api/alerts/rules/{rule['id']}")


async def test_preview_comes_first_and_cancel_writes_nothing(page, base_url, ui_env):
    posts: list[str] = []

    async def spy(route):
        posts.append(route.request.url)
        await route.continue_()

    with channels(ui_env, webhook=WEBHOOK):
        await page.route("**/api/places/notify-defaults", spy)
        await _open_places(page, base_url)
        assert re.search(
            r"\d+ places? (has|have) no arrival alerts\.",
            await page.inner_text("#fp-places-backfill"),
        )
        await page.click("#fp-places-backfill-btn")
        dialog = page.locator("#fp-confirm-dialog[open]")
        await dialog.wait_for()
        text = await dialog.inner_text()
        assert "Add arrival and departure alerts to" in text
        assert "Home: Webhook" in text
        assert ALERTS_LATENCY in text
        await dialog.get_by_role("button", name="Cancel").click()
        assert posts == [], "the preview is a dry run: nothing is written before the second click"
        rules = await (await page.request.get(base_url + "/api/alerts/rules")).json()
        assert not [r for r in rules if r["all_people"]]


async def test_confirming_adds_one_rule_per_place_and_clears_the_banner(page, base_url, ui_env):
    with channels(ui_env, webhook=WEBHOOK):
        try:
            await _open_places(page, base_url)
            await page.click("#fp-places-backfill-btn")
            await (
                page.locator("#fp-confirm-dialog[open]")
                .get_by_role("button", name="Add alerts")
                .click()
            )
            await page.wait_for_selector("#fp-places-backfill", state="hidden")
            rules = await (await page.request.get(base_url + "/api/alerts/rules")).json()
            home = [r for r in rules if r["place_name"] == "Home" and r["all_people"]]
            assert len(home) == 1 and home[0]["channels"] == ["webhook"] and home[0]["enabled"]
            await page.click('button[data-tab="alerts"]')
            row = page.locator("#fp-rules-tbody tr", has_text="Arrivals and departures at Home")
            await row.wait_for()
            text = await row.inner_text()
            assert "Everyone" in text and "anyone" in text, "an all-people rule names its subject"
        finally:
            await _drop_default_rules(page, base_url)


async def test_with_nothing_connected_the_preview_says_it_saves_switched_off(
    page, base_url, ui_env
):
    with channels(ui_env):
        try:
            await _open_places(page, base_url)
            await page.click("#fp-places-backfill-btn")
            text = await page.locator("#fp-confirm-dialog[open]").inner_text()
            assert "saved switched off" in text
            await page.get_by_role("button", name="Cancel").click()
        finally:
            await _drop_default_rules(page, base_url)


async def test_failed_preview_says_so(page, base_url, ui_env):
    with channels(ui_env, webhook=WEBHOOK):
        await _open_places(page, base_url)

        async def broken(route):
            await route.fulfill(
                status=500, content_type="application/json", body=json.dumps({"detail": "boom"})
            )

        await page.route("**/api/places/notify-defaults?dry_run=1", broken)
        await page.click("#fp-places-backfill-btn")
        await page.get_by_text("Could not check which places need alerts: boom").wait_for()

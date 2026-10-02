"""A damaged database shows a plain-words banner and says what to do."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

DAMAGED = "Find+ found damage in its history database, so it is read-only for now."


async def test_damaged_database_banner_leads_the_page(page, base_url):
    async def damaged(route):
        response = await route.fetch()
        body = json.loads(await response.text())
        body["database"] = {"ok": False, "problems": ["page 3 is damaged"]}
        await route.fulfill(response=response, body=json.dumps(body))

    await page.route("**/api/status*", damaged)
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")
    text = await page.locator("#app-shell").inner_text()
    assert DAMAGED in text
    assert "findplus db restore" in text


async def test_a_healthy_database_shows_no_banner(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")
    assert DAMAGED not in await page.locator("#app-shell").inner_text()

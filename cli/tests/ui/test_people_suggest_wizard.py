"""The setup wizard's Groups step shows the same "We found people" panel."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from ._suggest_helpers import serve
from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _post(page, base_url, key, value):
    await page.request.post(
        f"{base_url}/api/settings/{key}",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _unfinished(page, base_url):
    await _post(page, base_url, "onboarding.completed_at", None)
    await _post(page, base_url, "onboarding.last_step", "groups")
    try:
        yield
    finally:
        await _post(page, base_url, "onboarding.completed_at", SEEDED_COMPLETED_AT)
        await _post(page, base_url, "onboarding.last_step", None)


async def test_groups_step_offers_the_people_panel_and_accepts(page, base_url):
    _, posts = await serve(page)
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-people-suggest .ps-card", timeout=15000)
    assert "can group a person's trackers" in await page.inner_text("#fp-setup-people-suggest")
    assert await page.get_by_role("button", name="Not now").count() == 0, "the wizard has no hide"
    assert posts == []
    sam = page.locator("#fp-setup-people-suggest .ps-card", has_text="Sam (4 trackers")
    await sam.get_by_role("button", name="Accept", exact=True).click()
    await page.locator("#fp-setup-people-suggest").get_by_text("Created 1 person.").wait_for()
    assert posts[0]["accept"][0]["name"] == "Sam"
    assert await page.locator("#fp-setup-group-name").count() == 1, "the manual form is still there"

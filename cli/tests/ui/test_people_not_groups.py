"""People are not groups: the Groups tab cards, and the wizard step and summary."""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from ._person_helpers import ensure_person
from ._suggest_helpers import member, payload, serve
from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _groups_tab(page, base):
    await page.goto(base + "/")
    await page.wait_for_selector("#fp-add-group-btn", state="attached")
    await page.locator('button[data-tab="people"]').locator("visible=true").first.click()
    await page.wait_for_selector('[data-fp-ready="groups"]')


async def test_a_person_card_reads_plainly(trips_page, trips_server):
    pid = ensure_person(trips_server)
    p = trips_page
    await _groups_tab(p, trips_server["base"])
    card = p.locator(f'.fp-group-card[data-group-id="{pid}"]')
    await card.wait_for()
    await card.locator(".fp-card-explain:not([hidden])").wait_for()
    text = await card.inner_text()
    for banned in ("alerts when", "reporting", "members"):
        assert banned not in text
    assert "2 trackers" in text
    assert await card.locator(".fp-card-verdict").count() == 0


async def test_a_single_tracker_person_is_not_alarming(trips_page, trips_server):
    pid = ensure_person(trips_server)
    base = trips_server["base"]
    httpx.put(f"{base}/api/people/{pid}/members", json={"member_ids": ["TAG-SON"]})
    try:
        await _groups_tab(trips_page, base)
        card = trips_page.locator(f'.fp-group-card[data-group-id="{pid}"]')
        await card.locator(".fp-card-explain:not([hidden])").wait_for()
        text = await card.inner_text()
        assert "1 tracker" in text and "Only" not in text
        assert "fp-verdict--partial" not in await card.inner_html()
    finally:
        httpx.put(f"{base}/api/people/{pid}/members", json={"member_ids": ["TAG-SON", "TAG-MOM"]})


async def test_person_card_edit_opens_the_person_editor(trips_page, trips_server):
    pid = ensure_person(trips_server)
    p = trips_page
    await _groups_tab(p, trips_server["base"])
    await p.locator(f'.fp-group-card[data-group-id="{pid}"] .fp-card-edit').click()
    await p.wait_for_selector("#fp-person-dialog[open]")
    assert await p.locator("#fp-group-dialog[open]").count() == 0


async def _post(page, base_url, key, value):
    await page.request.post(
        f"{base_url}/api/settings/{key}",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


@pytest_asyncio.fixture(loop_scope="session")
async def unfinished(page, base_url):
    await _post(page, base_url, "onboarding.completed_at", None)
    try:
        yield
    finally:
        await _post(page, base_url, "onboarding.completed_at", SEEDED_COMPLETED_AT)
        await _post(page, base_url, "onboarding.last_step", None)


async def test_wizard_step_puts_people_above_groups_and_lists_unnamed_trackers(
    page, base_url, unfinished
):
    body = payload()
    body["unassigned"] = [
        {**member("u1", "Tag 4F2A", "other"), "question": "Whose is this?"},
        {**member("u2", "Unknown device", "other"), "question": "Whose is this?"},
    ]
    await _post(page, base_url, "onboarding.last_step", "groups")
    await serve(page, body)
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-people-suggest .ps-card", timeout=15000)
    assert (await page.inner_text("#setup-view h2")).strip() == "People and groups"
    whose = page.locator("#fp-setup-people-suggest .ps-whose-row")
    assert await whose.count() == 2
    assert await page.get_by_role("button", name="Accept all").count() == 0  # only Sam is ready
    people_y = (await page.locator("#fp-setup-people-suggest").bounding_box())["y"]
    groups_y = (await page.get_by_role("heading", name="Groups (optional)").bounding_box())["y"]
    assert people_y < groups_y


async def test_wizard_summary_counts_people_and_groups_apart(page, base_url, unfinished):
    people = [{"id": i, "kind": "person", "members": [], "name": f"P{i}"} for i in range(8)]
    group = {"id": 99, "kind": "set", "members": [], "name": "Trip"}

    async def groups(route):
        await route.fulfill(json=[*people, group])

    await page.route("**/api/groups", groups)
    await _post(page, base_url, "onboarding.last_step", "done")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view p[data-ready='true']", timeout=15000)
    assert "8 people, 1 group." in await page.inner_text("#setup-view")

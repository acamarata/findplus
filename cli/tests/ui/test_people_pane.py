"""People tab (1.3): person cards, Other groups, the suggestions card, Places buttons.

Inputs     : The trips fixture (Sam owns TAG-SON + TAG-MOM) for people, the seeded
             fixture (group "Family", place "Home") for groups and places.
Constraints: Headless only. A temporary person or pet is removed again after its test.
"""

from __future__ import annotations

import httpx
import pytest

from ._person_helpers import ensure_person
from ._suggest_helpers import serve
from .test_left_behind_chips import episode

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _people_tab(page, base):
    await page.goto(base + "/")
    await page.wait_for_selector("#fp-add-group-btn", state="attached")
    await page.click('.fp-tabs [data-tab="people"]')
    await page.wait_for_selector('[data-fp-ready="groups"]')


def _make(server, name, kind="person", members=()):
    body = {"name": name, "member_ids": list(members), "kind": kind}
    resp = httpx.post(f"{server['base']}/api/people", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_person_card_content_and_buttons(trips_page, trips_server):
    pid = ensure_person(trips_server)
    await _people_tab(trips_page, trips_server["base"])
    card = trips_page.locator(f'#fp-people-list .fp-person-card[data-group-id="{pid}"]')
    await card.locator(".fp-card-explain:not([hidden])").wait_for()
    assert await card.locator("button.person-avatar-btn").count() == 1
    assert "Sam" in await card.locator(".fp-card-name").inner_text()
    assert await card.locator(".fp-card-members .fp-avatar").count() == 2
    assert "2 trackers" in await card.inner_text()
    for hook, label, variant in (
        ("fp-card-open", "Open", "secondary"),
        ("fp-card-edit", "Edit", "secondary"),
        ("fp-card-delete", "Delete", "danger"),
    ):
        btn = card.locator(f"button.{hook}")
        assert (await btn.inner_text()).strip() == label
        assert f"fp-btn--{variant}" in await btn.get_attribute("class")
        assert await btn.locator("svg.fp-btn-icon[aria-hidden='true']").count() == 1


async def test_open_goes_to_the_person_page(trips_page, trips_server):
    pid = ensure_person(trips_server)
    await _people_tab(trips_page, trips_server["base"])
    await trips_page.locator(f'.fp-person-card[data-group-id="{pid}"] .fp-card-open').click()
    await trips_page.wait_for_function(f"location.hash.startsWith('#/person/{pid}')")


async def test_edit_opens_the_person_editor(trips_page, trips_server):
    pid = ensure_person(trips_server)
    await _people_tab(trips_page, trips_server["base"])
    await trips_page.locator(f'.fp-person-card[data-group-id="{pid}"] .fp-card-edit').click()
    await trips_page.wait_for_selector("#fp-person-dialog[open]")
    assert await trips_page.locator("#fp-group-dialog[open]").count() == 0


async def test_delete_confirms_then_removes_the_person(trips_page, trips_server):
    pid = _make(trips_server, "Temp Alex")
    try:
        await _people_tab(trips_page, trips_server["base"])
        card = trips_page.locator(f'.fp-person-card[data-group-id="{pid}"]')
        await card.locator(".fp-card-delete").click()
        dialog = trips_page.locator("#fp-confirm-dialog")
        await dialog.wait_for()
        await dialog.get_by_role("button", name="Cancel").click()
        assert await card.count() == 1
        await card.locator(".fp-card-delete").click()
        await dialog.get_by_role("button", name="Delete").click()
        await card.wait_for(state="detached")
    finally:
        httpx.delete(f"{trips_server['base']}/api/people/{pid}")


async def test_add_person_header_button_opens_the_editor(trips_page, trips_server):
    await _people_tab(trips_page, trips_server["base"])
    btn = trips_page.locator("#tab-people #fp-add-person-btn")
    assert (await btn.inner_text()).strip() == "Add person"
    assert "fp-btn--primary" in await btn.get_attribute("class")
    await btn.click()
    await trips_page.wait_for_selector("#fp-person-dialog[open]")


async def test_pet_uses_the_same_card_with_pet_wording(trips_page, trips_server):
    pid = _make(trips_server, "Biscuit", kind="pet", members=())
    try:
        await _people_tab(trips_page, trips_server["base"])
        card = trips_page.locator(f'#fp-people-list .fp-person-card[data-group-id="{pid}"]')
        await card.wait_for()
        assert "Pet" in await card.locator(".fp-card-meta").inner_text()
        assert await card.locator(".fp-card-open, .fp-card-edit, .fp-card-delete").count() == 3
    finally:
        httpx.delete(f"{trips_server['base']}/api/people/{pid}")


async def test_left_behind_chip_shows_on_the_card(trips_page, trips_server):
    pid = ensure_person(trips_server)

    async def left(route):
        await route.fulfill(json=[episode(1, "left_behind"), episode(2, "maybe")])

    await trips_page.route(f"**/api/people/{pid}/left-behind", left)
    await _people_tab(trips_page, trips_server["base"])
    chips = trips_page.locator(f'.fp-person-card[data-group-id="{pid}"] .fp-card-chip')
    await chips.first.wait_for()
    assert await chips.count() == 1
    assert "looks left at School" in await chips.first.inner_text()


async def test_suggestions_card_is_on_people_and_not_on_latest(trips_page, trips_server):
    await serve(trips_page)
    await trips_page.goto(trips_server["base"] + "/")
    await trips_page.wait_for_selector("#tab-latest:not([hidden])")
    await trips_page.click('.fp-tabs [data-tab="people"]')
    await trips_page.wait_for_selector("#tab-people #fp-people-banner:not([hidden])")
    assert "Find+ found 3 people" in await trips_page.inner_text("#fp-people-banner")
    await trips_page.wait_for_selector("#tab-people #fp-people-suggest .ps-card")
    assert await trips_page.locator("#tab-latest #fp-people-banner").count() == 0
    assert (
        await trips_page.locator("#tab-latest .ps-card, #tab-latest .people-suggest").count() == 0
    )


async def test_other_groups_section_has_add_edit_delete_buttons(page, base_url):
    await _people_tab(page, base_url)
    heading = page.locator("#fp-other-groups-heading")
    assert (await heading.text_content()).strip() == "Other groups"
    add = page.locator("#fp-add-group-btn")
    assert "fp-btn" in await add.get_attribute("class")
    card = page.locator("#fp-groups-list .fp-group-card", has_text="Family")
    await card.wait_for()
    assert "fp-btn--secondary" in await card.locator(".fp-card-edit").get_attribute("class")
    assert "fp-btn--danger" in await card.locator(".fp-card-delete").get_attribute("class")
    assert await page.locator("#fp-groups-list .person-avatar-btn").count() == 0


async def test_places_buttons_use_the_button_system(page, base_url):
    await page.goto(base_url + "/")
    await page.click('.fp-tabs [data-tab="places"]')
    add = page.locator("#fp-add-place-btn")
    await add.wait_for()
    assert "fp-btn--primary" in await add.get_attribute("class")
    card = page.locator("#fp-places-list .fp-place-card", has_text="Home")
    await card.wait_for()
    edit, delete = card.locator(".fp-card-edit"), card.locator(".fp-card-delete")
    assert "fp-btn--secondary" in await edit.get_attribute("class")
    assert "fp-btn--danger" in await delete.get_attribute("class")
    for btn in (edit, delete):
        assert await btn.locator("svg.fp-btn-icon[aria-hidden='true']").count() == 1
    notify = page.locator(".fp-place-notify-btn")
    if await notify.count():
        assert "fp-btn--secondary" in await notify.first.get_attribute("class")

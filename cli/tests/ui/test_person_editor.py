"""The person editor: name, kind, members with role and weight; saves through the people API."""

from __future__ import annotations

import httpx
import pytest

from ._person_helpers import ensure_person, open_person

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def pid(trips_server):
    return ensure_person(trips_server)


async def test_editor_saves_name_kind_role_and_weight(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    await p.get_by_role("button", name="Edit person").click()
    await p.wait_for_selector("#fp-person-dialog[open]")
    members = p.locator("#fp-person-dialog .pe-row")
    assert await members.count() == 2
    await p.fill("#fp-person-name", "Sammy")
    await p.locator("#fp-person-dialog input[value=pet]").check()
    row = members.filter(has_text="Mia")
    await row.locator("select.pe-role").select_option("keys")
    await row.locator("select.pe-weight").select_option(label="Sometimes carries it")
    await p.locator("#fp-person-dialog footer").get_by_role("button", name="Save").click()
    await p.wait_for_selector("#fp-person-dialog", state="hidden")
    await p.wait_for_selector(".person-name:has-text('Sammy')")
    got = httpx.get(f"{trips_server['base']}/api/people/{pid}").json()
    assert (got["name"], got["kind"]) == ("Sammy", "pet")
    mia = next(x for x in got["trackers"] if x["device_id"] == "TAG-MOM")
    assert (mia["role"], mia["carry_weight"]) == ("keys", 0.4)
    httpx.patch(f"{trips_server['base']}/api/people/{pid}", json={"name": "Sam", "kind": "person"})
    httpx.put(
        f"{trips_server['base']}/api/people/trackers/TAG-MOM",
        json={"role": "bag", "carry_weight": None},
    )


async def test_editor_needs_a_name_and_a_tracker(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    await p.get_by_role("button", name="Edit person").click()
    await p.wait_for_selector("#fp-person-dialog[open]")
    for box in await p.locator("#fp-person-dialog .pe-row input[type=checkbox]").all():
        await box.uncheck()
    await p.locator("#fp-person-dialog footer").get_by_role("button", name="Save").click()
    await p.get_by_text("Pick at least one tracker.").wait_for()
    assert await p.locator("#fp-person-dialog[open]").count() == 1


async def test_editor_is_keyboard_reachable_and_escape_closes_it(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    await p.get_by_role("button", name="Edit person").focus()
    await p.keyboard.press("Enter")
    await p.wait_for_selector("#fp-person-dialog[open]")
    assert await p.evaluate("document.activeElement.id") == "fp-person-name"
    await p.keyboard.press("Escape")
    await p.wait_for_selector("#fp-person-dialog", state="hidden")

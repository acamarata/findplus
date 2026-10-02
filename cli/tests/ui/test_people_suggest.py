"""The "We found people in your trackers" panel: preview, answers, accept all, hide, re-check."""

from __future__ import annotations

import pytest

from ._person_helpers import errors_of
from ._suggest_helpers import payload, serve

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_groups(page, server):
    page.fp_errors = errors_of(page)
    await page.goto(server["base"] + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]")
    await page.click('button[data-tab="groups"]')
    await page.wait_for_selector("#fp-people-suggest .ps-card")


async def test_cards_preview_each_guess_and_apply_nothing(trips_page, trips_server):
    _, posts = await serve(trips_page)
    await _open_groups(trips_page, trips_server)
    p = trips_page
    titles = await p.locator(".ps-title").all_inner_texts()
    assert titles[0] == "Sam (4 trackers: Sam Bag, Sam Bike, Sam Shoes Red, Sam Shoes White)"
    sam = p.locator(".ps-card", has_text="Sam (4 trackers")
    for name in ("Accept", "Edit members", "Not a person", "It's a pet"):
        assert await sam.get_by_role("button", name=name, exact=True).count() == 1
    whiskers = p.locator(".ps-card", has_text="Whiskers")
    assert "Is Whiskers a person or a pet?" in await whiskers.inner_text()
    assert await whiskers.get_by_role("button", name="Accept", exact=True).count() == 0
    assert "colour or brand" in await p.locator(".ps-card", has_text="Rose").inner_text()
    assert "Whose is this?" in await p.inner_text(".ps-whose")
    assert posts == [], "a guess is never applied without a click"


async def test_accept_posts_the_exact_guess(trips_page, trips_server):
    _, posts = await serve(trips_page)
    await _open_groups(trips_page, trips_server)
    await (
        trips_page.locator(".ps-card", has_text="Sam (4 trackers")
        .get_by_role("button", name="Accept", exact=True)
        .click()
    )
    await trips_page.get_by_text("Added 1 person.").wait_for()
    assert posts[0]["accept"][0]["name"] == "Sam" and posts[0]["accept"][0]["kind"] == "person"
    assert [m["device_id"] for m in posts[0]["accept"][0]["members"]] == ["z1", "z2", "z3", "z4"]
    assert posts[0]["dismiss"] == []
    assert trips_page.fp_errors == []


async def test_person_or_pet_question_decides_the_kind(trips_page, trips_server):
    _, posts = await serve(trips_page)
    await _open_groups(trips_page, trips_server)
    await (
        trips_page.locator(".ps-card", has_text="Whiskers")
        .get_by_role("button", name="It's a pet")
        .click()
    )
    await trips_page.get_by_text("Added 1 person.").wait_for()
    assert posts[0]["accept"][0]["kind"] == "pet" and posts[0]["accept"][0]["name"] == "Whiskers"


async def test_not_a_person_dismisses_by_key(trips_page, trips_server):
    _, posts = await serve(trips_page, accept_reply={"people": [], "dismissed": ["create:rose"]})
    await _open_groups(trips_page, trips_server)
    await (
        trips_page.locator(".ps-card", has_text="Rose")
        .get_by_role("button", name="Not a person")
        .click()
    )
    await trips_page.get_by_text("will not suggest that again").wait_for()
    assert posts[0] == {"accept": [], "dismiss": ["create:rose"]}


async def test_accept_all_skips_what_still_needs_an_answer(trips_page, trips_server):
    body = payload()
    body["suggestions"].append(
        {
            **body["suggestions"][0],
            "key": "create:ali",
            "name": "Ali",
            "members": [
                {"device_id": "a1", "name": "Ali Keys", "role": "keys", "confidence": "high"}
            ],
        }
    )
    _, posts = await serve(trips_page, body=body)
    await _open_groups(trips_page, trips_server)
    btn = trips_page.get_by_role("button", name="Accept all (2)")
    await btn.click()
    await trips_page.get_by_text("Added 1 person.").wait_for()
    assert [a["name"] for a in posts[0]["accept"]] == ["Sam", "Ali"], (
        "Whiskers (asks) and Rose (low confidence) are left"
    )


async def test_edit_members_changes_name_and_trackers_before_accepting(trips_page, trips_server):
    _, posts = await serve(trips_page)
    await _open_groups(trips_page, trips_server)
    card = trips_page.locator(".ps-card", has_text="Sam (4 trackers")
    await card.get_by_role("button", name="Edit members").click()
    await card.get_by_label("Sam Bike").uncheck()
    await card.get_by_label("Name").fill("Zed")
    await card.get_by_role("button", name="Save and accept").click()
    await trips_page.get_by_text("Added 1 person.").wait_for()
    sent = posts[0]["accept"][0]
    assert sent["name"] == "Zed" and [m["device_id"] for m in sent["members"]] == ["z1", "z3", "z4"]


async def test_whose_is_this_adds_to_a_new_person(trips_page, trips_server):
    _, posts = await serve(trips_page)
    await _open_groups(trips_page, trips_server)
    row = trips_page.locator(".ps-whose-row")
    assert await row.get_by_role("button", name="Add").is_disabled()
    await row.locator("select").select_option("new")
    await row.get_by_placeholder("New person's name").fill("Ali")
    await row.get_by_role("button", name="Add").click()
    await trips_page.get_by_text("Added 1 person.").wait_for()
    assert posts[0]["accept"][0] == {
        "action": "create",
        "name": "Ali",
        "kind": "person",
        "group_id": None,
        "members": [{"device_id": "p1", "role": "phone"}],
    }


async def test_hide_remembers_until_new_suggestions_and_recheck_refetches(trips_page, trips_server):
    gets, _ = await serve(trips_page)
    await _open_groups(trips_page, trips_server)
    p = trips_page
    await p.get_by_role("button", name="Not now").click()
    await p.get_by_role("button", name="Show suggestions (3)").wait_for()
    await p.reload()
    await p.wait_for_selector("#app-shell[data-fp-ready]")
    await p.click('button[data-tab="groups"]')
    await p.get_by_role("button", name="Show suggestions (3)").wait_for()
    before = len(gets)
    await p.get_by_role("button", name="Check again").click()
    await p.get_by_role("button", name="Show suggestions (3)").wait_for()
    assert len(gets) > before


async def test_dashboard_banner_counts_and_opens_the_panel(trips_page, trips_server):
    await serve(trips_page)
    await trips_page.goto(trips_server["base"] + "/")
    await trips_page.wait_for_selector("#fp-people-banner:not([hidden])")
    assert "Find+ found 3 people in your trackers." in await trips_page.inner_text(
        "#fp-people-banner"
    )
    await trips_page.get_by_role("button", name="Review").click()
    await trips_page.wait_for_selector("#tab-groups:not([hidden]) .ps-card")


async def test_error_state_retries(trips_page, trips_server):
    state = {"fail": True}

    async def suggestions(route):
        if state["fail"]:
            await route.fulfill(status=500, json={"detail": "boom"})
        else:
            await route.fulfill(json=payload())

    await trips_page.route("**/api/people/suggestions", suggestions)
    await trips_page.goto(trips_server["base"] + "/")
    await trips_page.wait_for_selector("#app-shell[data-fp-ready]")
    await trips_page.click('button[data-tab="groups"]')
    await trips_page.get_by_text("Could not look for people").wait_for()
    state["fail"] = False
    await trips_page.locator("#fp-people-suggest").get_by_role("button", name="Retry").click()
    await trips_page.wait_for_selector("#fp-people-suggest .ps-card")


async def test_real_server_round_trip_creates_the_person(trips_page, trips_server):
    p = trips_page
    await p.goto(trips_server["base"] + "/")
    await p.wait_for_selector("#app-shell[data-fp-ready]")
    await p.click('button[data-tab="groups"]')
    card = p.locator(".ps-card", has_text="Sam")
    await card.wait_for()
    await card.get_by_role("button", name="It's a person").click()
    await p.get_by_text("Added 1 person.").wait_for()
    link = p.locator(".fp-group-card a.person-link", has_text="Sam")
    await link.wait_for()
    assert (await link.get_attribute("href")).startswith("#/person/")

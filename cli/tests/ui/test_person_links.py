"""A person's name opens their page wherever it is printed, and a tracker's name never does."""

# ruff: noqa: E501

from __future__ import annotations

import json

import pytest

from ._person_helpers import ensure_person

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _boot(page, server):
    await page.goto(server["base"] + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]")
    await page.wait_for_function("document.querySelectorAll('a.person-link').length >= 0")


async def test_group_card_name_links_to_the_person(trips_page, trips_server):
    pid = ensure_person(trips_server)
    p = trips_page
    await _boot(p, trips_server)
    await p.click('button[data-tab="groups"]')
    link = p.locator(f'.fp-group-card[data-group-id="{pid}"] a.person-link')
    await link.wait_for()
    assert await link.get_attribute("href") == f"#/person/{pid}"
    await link.click()
    await p.wait_for_selector("#tab-person:not([hidden])")
    assert (await p.inner_text(".person-name")).startswith("Sam")
    assert await p.locator(".fp-group-card a.person-link").count() >= 1


async def test_a_set_group_name_is_not_a_link(trips_page, trips_server):
    ensure_person(trips_server)
    await _boot(trips_page, trips_server)
    await trips_page.click('button[data-tab="groups"]')
    card = trips_page.locator(".fp-group-card", has_text="Family")
    await card.wait_for()
    assert await card.locator("a.person-link").count() == 0


async def test_rule_sentence_links_the_person(trips_page, trips_server):
    pid = ensure_person(trips_server)
    base = trips_server["base"]
    body = {
        "name": "Sam at School",
        "group_id": pid,
        "place_id": 2,
        "channels": ["native"],
        "cooldown_minutes": 0,
    }
    r = await trips_page.request.post(
        base + "/api/alerts/rules",
        data=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )
    assert r.ok, await r.text()
    rule_id = (await r.json())["id"]
    try:
        await _boot(trips_page, trips_server)
        await trips_page.click('button[data-tab="alerts"]')
        row = trips_page.locator("#fp-rules-tbody tr", has_text="Sam at School")
        await row.wait_for()
        link = row.locator(".fp-rule-row-sentence a.person-link")
        await link.wait_for()
        assert await link.get_attribute("href") == f"#/person/{pid}"
    finally:
        await trips_page.request.delete(f"{base}/api/alerts/rules/{rule_id}")


async def test_text_linker_rules(trips_page, trips_server):
    people = [
        {
            "id": 7,
            "name": "Zaid",
            "kind": "person",
            "trackers": [{"device_id": "x", "name": "Zaid Bag"}],
        }
    ]

    async def mocked(route):
        await route.fulfill(json=people)

    await _boot(trips_page, trips_server)
    await trips_page.route("**/api/people", mocked)
    out = await trips_page.evaluate(
        """async () => {
          const m = await import('/static/app/person_links.js');
          await m.refreshPeopleCache();
          const cases = ['Zaid arrived at School', "Zaid's bag looks left", 'Zaid Bag left Home', 'Zaidan left', 'Seen by Zaid Bag, Zaid left'];
          return cases.map((c) => { const d = document.createElement('div'); d.textContent = c; m.linkPeople(d); return [c, d.querySelectorAll('a.person-link').length, d.textContent]; });
        }"""
    )
    got = {c: n for c, n, _ in out}
    assert got["Zaid arrived at School"] == 1 and got["Zaid's bag looks left"] == 1
    assert got["Zaid Bag left Home"] == 0, "a tracker named Zaid Bag is not the person"
    assert got["Zaidan left"] == 0, "whole words only"
    assert got["Seen by Zaid Bag, Zaid left"] == 1, "only the person is linked, not the tracker"
    assert all(text == c for c, _, text in out), "the text itself never changes"


async def test_links_are_keyboard_reachable(trips_page, trips_server):
    pid = ensure_person(trips_server)
    await _boot(trips_page, trips_server)
    await trips_page.click('button[data-tab="groups"]')
    link = trips_page.locator(f'.fp-group-card[data-group-id="{pid}"] a.person-link')
    await link.focus()
    await trips_page.keyboard.press("Enter")
    await trips_page.wait_for_selector("#tab-person:not([hidden])")

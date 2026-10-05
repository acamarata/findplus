"""After Accept all: say what was created; and show "Updating past days..." while a replay runs."""

from __future__ import annotations

import json

import pytest

from ._suggest_helpers import _suggestion, member, payload

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_groups(page, server):
    page.fp_errors = []
    page.on("pageerror", lambda e: page.fp_errors.append(str(e)))
    await page.goto(server["base"] + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]")
    await page.click('button[data-tab="people"]')
    await page.wait_for_selector("#fp-people-suggest .ps-card")


async def _serve_five(page):
    names = ["Sam", "Robin", "Jamie", "Kai", "Drew"]
    many = [
        _suggestion(f"create:{n.lower()}", n, [member(f"m{i}", f"{n} Bag", "bag")])
        for i, n in enumerate(names)
    ]
    body = {**payload(), "suggestions": many, "unassigned": []}
    state = {"done": False}

    async def suggestions(route):
        empty = {**body, "suggestions": []}
        await route.fulfill(json=empty if state["done"] else body)

    async def accept(route):
        state["done"] = True
        people = [{"id": i + 10, "name": n} for i, n in enumerate(names)]
        await route.fulfill(json={"people": people, "dismissed": []})

    await page.route("**/api/people/suggestions", suggestions)
    await page.route("**/api/people/suggestions/accept", accept)


async def test_accept_all_says_created_5_people_not_no_new_people(trips_page, trips_server):
    await _serve_five(trips_page)
    await _open_groups(trips_page, trips_server)
    await trips_page.get_by_role("button", name="Accept all (5)").click()
    await trips_page.get_by_text("Created 5 people.").wait_for()
    assert "No new people found" not in await trips_page.inner_text("#fp-people-suggest")


async def test_updating_past_days_line_shows_while_a_replay_runs(trips_page, trips_server):
    await _serve_five(trips_page)
    calls = {"n": 0}

    async def replay(route):
        calls["n"] += 1
        if calls["n"] < 3:
            await route.fulfill(json={"state": "running", "done": 2, "total": 10})
        else:
            await route.fulfill(json={"state": "done", "done": 10, "total": 10})

    await trips_page.route("**/api/people/replay", replay)
    await _open_groups(trips_page, trips_server)
    await trips_page.get_by_role("button", name="Accept all (5)").click()
    await trips_page.get_by_text("Updating past days... 2 of 10").wait_for()
    assert await trips_page.get_attribute("#fp-replay-line", "role") == "status"
    await trips_page.wait_for_selector("#fp-replay-line", state="detached", timeout=15000)


async def test_a_daemon_without_the_replay_route_shows_nothing(trips_page, trips_server):
    await _serve_five(trips_page)
    seen = []

    async def missing(route):
        seen.append(1)
        await route.fulfill(status=404, body=json.dumps({"detail": "Not Found"}))

    await trips_page.route("**/api/people/replay", missing)
    await _open_groups(trips_page, trips_server)
    await trips_page.get_by_role("button", name="Accept all (5)").click()
    await trips_page.get_by_text("Created 5 people.").wait_for()
    await trips_page.wait_for_timeout(800)
    assert await trips_page.locator("#fp-replay-line").count() == 0
    assert len(seen) == 1
    assert trips_page.fp_errors == []

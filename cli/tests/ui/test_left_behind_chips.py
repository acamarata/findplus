"""The dashboard's left-behind notices: honest wording, "I know", and the way to the person's day."""

# ruff: noqa: E501

from __future__ import annotations

import pytest

from ._person_helpers import ensure_person

pytestmark = pytest.mark.asyncio(loop_scope="session")


def episode(i: int, state: str, place: str | None = "School") -> dict:
    return {
        "id": i,
        "person_id": 1,
        "device_id": "TAG-MOM",
        "device_name": "Mia",
        "place_id": 2 if place else None,
        "place_name": place,
        "latitude": 41.13,
        "longitude": -80.08,
        "state": state,
        "started_observed_at": "2026-10-01T15:00:00+00:00",
        "confirmed_at": "2026-10-01T15:20:00+00:00",
        "cleared_at": None,
        "clear_reason": None,
        "notified_at": None,
    }


async def _serve(page, pid, episodes, dismissed=None, fail=False):
    async def left(route):
        await route.fulfill(json=episodes)

    async def dismiss(route):
        if fail:
            await route.fulfill(status=500, json={"detail": "boom"})
            return
        dismissed.append(route.request.url.split("/left-behind/")[1].split("/")[0])
        await route.fulfill(json={**episodes[0], "state": "cleared"})

    await page.route(f"**/api/people/{pid}/left-behind", left)
    await page.route(f"**/api/people/{pid}/left-behind/*/dismiss", dismiss)


async def _open(page, server):
    await page.goto(server["base"] + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]")


async def test_only_a_confirmed_episode_shows_and_it_admits_it_is_a_guess(trips_page, trips_server):
    pid = ensure_person(trips_server)
    eps = [episode(1, "left_behind"), episode(2, "apart_pending", None), episode(3, "cleared")]
    await _serve(trips_page, pid, eps, [])
    await _open(trips_page, trips_server)
    box = trips_page.locator("#fp-left-behind")
    await box.wait_for(state="visible")
    text = await box.inner_text()
    assert "Sam's bag looks left at School since 3:00 PM." in text
    assert "cannot be sure" in text and "parked on purpose" in text
    assert await box.locator(".lb-row").count() == 1, (
        "a maybe and a cleared episode stay off the dashboard"
    )


async def test_i_know_dismisses_and_hides_the_box(trips_page, trips_server):
    pid = ensure_person(trips_server)
    dismissed: list[str] = []
    await _serve(trips_page, pid, [episode(1, "left_behind")], dismissed)
    await _open(trips_page, trips_server)
    await trips_page.get_by_role("button", name="I know").click()
    await trips_page.wait_for_selector("#fp-left-behind", state="hidden")
    assert dismissed == ["1"]


async def test_a_refused_dismiss_keeps_the_row_and_says_why(trips_page, trips_server):
    pid = ensure_person(trips_server)
    await _serve(trips_page, pid, [episode(1, "left_behind")], [], fail=True)
    await _open(trips_page, trips_server)
    await trips_page.get_by_role("button", name="I know").click()
    await trips_page.get_by_text("Could not save that: boom").wait_for()
    assert await trips_page.locator(".lb-row").count() == 1
    assert await trips_page.get_by_role("button", name="I know").is_enabled()


async def test_the_row_links_to_the_persons_day(trips_page, trips_server):
    pid = ensure_person(trips_server)
    await _serve(trips_page, pid, [episode(1, "left_behind", None)], [])
    await _open(trips_page, trips_server)
    assert "looks left behind since 3:00 PM" in await trips_page.inner_text("#fp-left-behind")
    await trips_page.get_by_role("link", name="See Sam's day").click()
    await trips_page.wait_for_selector("#tab-person:not([hidden]) .person-name")


async def test_nothing_to_report_leaves_the_box_hidden(trips_page, trips_server):
    pid = ensure_person(trips_server)
    await _serve(trips_page, pid, [], [])
    await _open(trips_page, trips_server)
    assert await trips_page.locator("#fp-left-behind").is_hidden()

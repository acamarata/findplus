"""The Person page's states: loading, empty day, partial, error with Retry, offline, no such person, locked."""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

from ._person_helpers import ensure_person, open_person, stub_day

pytestmark = pytest.mark.asyncio(loop_scope="session")
PIN = "864213"


@pytest.fixture
def pid(trips_server):
    return ensure_person(trips_server)


async def test_empty_day_says_so_and_still_lists_trackers(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid, day_key="empty")
    p = trips_page
    assert "No sightings on this day" in await p.inner_text("[data-person-state=empty]")
    assert await p.locator(".person-tracker").count() == 2
    assert await p.locator(".lane").count() == 0, "no story for a day with no sightings"


async def test_summary_failure_is_partial_not_fatal(trips_page, trips_server, pid):
    await stub_day(trips_page, pid, fail=True)
    await open_person(trips_page, trips_server, pid, stub=False)
    p = trips_page
    assert "day summary is not available" in await p.inner_text(".person-summary")
    assert await p.locator(".story-item").count() > 0, "the map and story still work"


async def test_one_tracker_failing_says_which(trips_page, trips_server, pid):
    async def trips(route):
        if "TAG-MOM" in route.request.url:
            await route.fulfill(status=500, json={"detail": "boom"})
        else:
            await route.continue_()

    await trips_page.route("**/api/trips?*", trips)
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    note = await p.inner_text(".person-partial")
    assert "could not be loaded" in note and "Mia" in note
    assert "incomplete" in note


async def test_error_then_retry_then_offline(trips_page, trips_server, pid):
    state = {"mode": "fail"}

    async def timeline(route):
        if state["mode"] == "fail":
            await route.fulfill(status=500, json={"detail": "boom"})
        elif state["mode"] == "offline":
            await route.abort()
        else:
            await route.continue_()

    await trips_page.route("**/api/timeline?group_id=*", timeline)
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    await p.get_by_text("Could not load Sam's day").wait_for()
    state["mode"] = "ok"
    await p.get_by_role("button", name="Retry").click()
    await p.wait_for_selector(".person-tracker")
    state["mode"] = "offline"
    await p.click("#person-prev")
    await p.get_by_text("Find+ is not responding").wait_for()


async def test_unknown_person_has_its_own_state(trips_page, trips_server):
    await trips_page.goto(f"{trips_server['base']}/#/person/9999")
    await trips_page.get_by_text("This person is not here any more").wait_for()
    await trips_page.click("[data-person-state=notfound] a")
    await trips_page.wait_for_selector("#tab-dashboard", state="visible")


async def test_loading_state_is_announced(trips_page, trips_server, pid):
    async def slow(route):
        await asyncio.sleep(0.6)
        await route.continue_()

    await trips_page.route("**/api/people/*/now", slow)
    await stub_day(trips_page, pid)
    await trips_page.goto(
        f"{trips_server['base']}/#/person/{pid}?date={trips_server['days']['school']}"
    )
    skeleton = trips_page.locator("#person-body .skeleton")
    await skeleton.wait_for()
    assert "Loading" in (await skeleton.get_attribute("aria-label"))
    await trips_page.wait_for_selector(".person-tracker")
    await trips_page.unroute_all(behavior="ignoreErrors")


async def _lock_on(page, base):
    h = {"Content-Type": "application/json"}
    assert (
        await page.request.post(
            f"{base}/api/settings/pin", data=json.dumps({"new_pin": PIN}), headers=h
        )
    ).ok
    assert (
        await page.request.patch(
            f"{base}/api/settings", data=json.dumps({"lock_enabled": True}), headers=h
        )
    ).ok


async def _lock_off(page, base):
    h = {"Content-Type": "application/json"}
    with contextlib.suppress(Exception):
        await page.request.post(f"{base}/api/lock/unlock", data=json.dumps({"pin": PIN}), headers=h)
    await page.request.delete(
        f"{base}/api/settings/pin", data=json.dumps({"current_pin": PIN}), headers=h
    )


async def test_lock_purges_names_times_and_coordinates(trips_page, trips_server, pid):
    base = trips_server["base"]
    await _lock_on(trips_page, base)
    try:
        await open_person(trips_page, trips_server, pid)
        p = trips_page
        await p.click("#person-prev")
        await p.wait_for_selector(".person-tracker")
        await p.click("#btn-lock")
        await p.wait_for_selector("#lock-screen:not(.hidden)")
        text = await p.evaluate(
            "document.body.textContent + [...document.querySelectorAll('[title],[aria-label]')].map(e => e.title + e.getAttribute('aria-label')).join('')"
        )
        for leaked in ("Sam", "Mia", "School", "8:10 AM", "arrived at"):
            assert leaked not in text, f"{leaked!r} survived the lock"
        assert await p.locator("#map svg path.leaflet-interactive").count() == 0
        assert await p.input_value("#person-date") == ""
        await p.fill("#lock-pin", PIN)
        await p.click("#lock-submit")
        await p.wait_for_selector(".person-tracker")
    finally:
        await _lock_off(trips_page, base)

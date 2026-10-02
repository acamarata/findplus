"""Settings: daily summary controls, the left-behind switch and the backup line."""

from __future__ import annotations

import asyncio
import json

import pytest

from ._person_helpers import ensure_person, errors_of

pytestmark = pytest.mark.asyncio(loop_scope="session")
OFF = {"enabled": False, "time": "20:00", "people": [], "channel": "auto", "always_send": False}


async def _stub_settings(page):
    """GET /api/settings gains `people.digest`; PATCH merges it and records the call."""
    digest = dict(OFF)
    patches: list[dict] = []

    async def handler(route):
        try:
            real = await route.fetch()
            body = await real.json()
            if route.request.method == "PATCH":
                sent = json.loads(route.request.post_data)
                patches.append(sent)
                digest.update(sent.get("people.digest", {}))
            await route.fulfill(json={**body, "people.digest": dict(digest)})
        except Exception:  # the page closed while a request was in flight
            return

    await page.route("**/api/settings", handler)
    return patches


async def _until(check, seconds: float = 5.0):
    for _ in range(int(seconds / 0.05)):
        if check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the save never reached the server")


async def _open_settings(page, server):
    page.fp_errors = errors_of(page)
    await page.goto(server["base"] + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]")
    await page.click("#btn-settings")
    await page.wait_for_selector("#fp-settings-people h3")
    await page.wait_for_selector("#person-backup-line:not(:empty)")


async def test_digest_is_off_by_default_and_says_where_it_goes(trips_page, trips_server):
    ensure_person(trips_server)
    await _stub_settings(trips_page)
    await _open_settings(trips_page, trips_server)
    p = trips_page
    assert not await p.is_checked("#person-digest-on")
    text = await p.inner_text("#fp-settings-people")
    assert "no coordinates" in text and "off until you turn it on" in text
    assert "Alerts inherit the network's delay." in text
    assert "A tag with no recent fix is stale" in text


async def test_each_control_saves_as_it_changes(trips_page, trips_server):
    ensure_person(trips_server)
    patches = await _stub_settings(trips_page)
    await _open_settings(trips_page, trips_server)
    p = trips_page
    await p.check("#person-digest-on")
    await _until(lambda: len(patches) == 1)
    await p.fill("#person-digest-time", "19:30")
    await p.press("#person-digest-time", "Tab")
    await _until(lambda: len(patches) == 2)
    await p.select_option("#person-digest-channel", "telegram")
    await _until(lambda: len(patches) == 3)
    assert await p.inner_text("#settings-saved") == "Saved."
    assert [next(iter(x["people.digest"].items())) for x in patches] == [
        ("enabled", True),
        ("time", "19:30"),
        ("channel", "telegram"),
    ]


async def test_turning_the_last_person_off_turns_the_summary_off(trips_page, trips_server):
    ensure_person(trips_server)
    patches = await _stub_settings(trips_page)
    await _open_settings(trips_page, trips_server)
    p = trips_page
    await p.check("#person-digest-on")
    await p.locator(".person-digest-row input[type=checkbox]").first.uncheck()
    await p.get_by_text("Pick at least one person").wait_for()
    assert not await p.is_checked("#person-digest-on")
    await _until(lambda: len(patches) == 2)
    assert patches[-1] == {"people.digest": {"enabled": False}}


async def test_send_now_reports_the_result(trips_page, trips_server):
    pid = ensure_person(trips_server)
    await _stub_settings(trips_page)

    async def send(route):
        await route.fulfill(
            json={"sent": True, "channel": "telegram", "targets": [{"target": "1", "ok": True}]}
        )

    await trips_page.route(f"**/api/people/{pid}/day/send", send)
    await _open_settings(trips_page, trips_server)
    await trips_page.get_by_role("button", name="Send Sam's day now").click()
    await trips_page.get_by_text("Sent to Telegram.").wait_for()


async def test_left_behind_switch_persists(trips_page, trips_server):
    ensure_person(trips_server)
    await _stub_settings(trips_page)
    await _open_settings(trips_page, trips_server)
    p = trips_page
    assert await p.is_checked("#person-left-on"), "on by default"
    await p.uncheck("#person-left-on")
    await p.wait_for_function("document.querySelector('#settings-saved').textContent === 'Saved.'")
    got = await p.evaluate("fetch('/api/people/settings').then(r => r.json())")
    assert got["left_behind_alerts"] is False
    await p.check("#person-left-on")


async def test_backup_line_and_back_up_now(trips_page, trips_server):
    ensure_person(trips_server)
    await _stub_settings(trips_page)
    await _open_settings(trips_page, trips_server)
    p = trips_page
    before = await p.inner_text("#person-backup-line")
    assert "Last backup" in before and "(automatic)" in before, "the daemon takes one at start"
    await p.click("#person-backup-now")
    await p.get_by_text("Backup saved.").wait_for()
    line = await p.inner_text("#person-backup-line")
    assert "(manual)" in line and "2 kept" in line
    assert "never your sign-ins or tokens" in await p.inner_text("#fp-settings-people")
    assert p.fp_errors == []


async def test_no_backup_yet_says_so(trips_page, trips_server):
    ensure_person(trips_server)
    await _stub_settings(trips_page)

    async def none(route):
        await route.fulfill(
            json={"directory": "x", "count": 0, "last_backup_at": None, "last_kind": None}
        )

    await trips_page.route("**/api/settings/backup", none)
    await _open_settings(trips_page, trips_server)
    assert "No backup yet" in await trips_page.inner_text("#person-backup-line")


async def test_backup_failure_says_why(trips_page, trips_server):
    ensure_person(trips_server)
    await _stub_settings(trips_page)

    async def broken(route):
        await route.fulfill(status=500, json={"detail": "The disk is full."})

    await trips_page.route("**/api/settings/backup/now", broken)
    await _open_settings(trips_page, trips_server)
    await trips_page.click("#person-backup-now")
    await trips_page.get_by_text("Could not back up: The disk is full.").wait_for()

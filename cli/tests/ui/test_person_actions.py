"""Person page actions: send the day, edit a tracker's role and weight, Notify me, Edit, Full map."""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json

import pytest

from ._person_helpers import ensure_person, open_person

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def pid(trips_server):
    return ensure_person(trips_server)


async def _send_route(page, reply, seen):
    async def handler(route):
        seen.append(json.loads(route.request.post_data or "{}"))
        await asyncio.sleep(0.25)
        await route.fulfill(**reply)

    await page.route("**/api/people/*/day/send", handler)


async def test_send_reports_where_it_went_and_posts_once(trips_page, trips_server, pid):
    seen: list = []
    await _send_route(
        trips_page,
        {
            "json": {
                "sent": True,
                "channel": "telegram",
                "targets": [{"target": "42", "ok": True, "error": None}],
            }
        },
        seen,
    )
    day = await open_person(trips_page, trips_server, pid)
    p = trips_page
    assert "Send this day's summary" in await p.inner_text("#person-send")
    await p.click("#person-send")
    assert await p.is_disabled("#person-send"), "no second click while the first is out"
    await p.get_by_text("Sent to Telegram.").wait_for()
    assert seen == [{"date": day}]
    assert await p.is_enabled("#person-send")


async def test_send_with_one_chat_refusing_says_so(trips_page, trips_server, pid):
    targets = [{"target": "1", "ok": True}, {"target": "2", "ok": False, "error": "kicked"}]
    reply = {"json": {"sent": True, "channel": "telegram", "targets": targets}}
    await _send_route(trips_page, reply, [])
    await open_person(trips_page, trips_server, pid)
    await trips_page.click("#person-send")
    await trips_page.get_by_text("Sent to Telegram. 1 chat did not accept it.").wait_for()


async def test_send_failure_says_why(trips_page, trips_server, pid):
    await _send_route(
        trips_page, {"status": 409, "json": {"detail": "Telegram is not connected"}}, []
    )
    await open_person(trips_page, trips_server, pid)
    await trips_page.click("#person-send")
    await trips_page.get_by_text("Could not send: Telegram is not connected").wait_for()
    assert "person-status--err" in await trips_page.get_attribute("#person-status", "class")


async def test_send_today_label(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    await trips_page.click("#person-today")
    await trips_page.wait_for_function(
        "document.querySelector('#person-send').textContent.includes('today')"
    )


async def test_tracker_edit_saves_role_and_weight(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    row = p.locator(".person-tracker", has_text="Mia")
    await row.get_by_role("button", name="Edit Mia").click()
    assert await row.get_by_role("button", name="Edit Mia").get_attribute("aria-expanded") == "true"
    await row.locator("select").select_option("keys")
    await row.locator("input[type=number]").fill("0.35")
    await row.get_by_role("button", name="Save").click()
    meta = p.locator(".person-tracker", has_text="Mia").locator(".person-tracker-meta")
    await meta.get_by_text("keys · weight 0.35").wait_for()
    got = await p.evaluate(
        "fetch('/api/people/trackers/TAG-MOM', {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({role:'bag', carry_weight:null})}).then(r => r.json())"
    )
    assert got["role"] == "bag"


async def test_tracker_editor_is_keyboard_reachable_and_cancels(trips_page, trips_server, pid):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    row = p.locator(".person-tracker").first
    edit = row.locator(".person-tracker-edit")
    await edit.focus()
    await p.keyboard.press("Enter")
    assert await p.evaluate("document.activeElement.tagName") == "SELECT"
    await row.get_by_role("button", name="Cancel").click()
    assert await row.locator(".person-edit").count() == 0
    assert await p.evaluate("document.activeElement.classList.contains('person-tracker-edit')")


async def test_notify_me_is_one_tap_with_a_preview(trips_page, trips_server, pid):
    """No name or device prompts: a preview of what is added, one confirm, then a sentence."""
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    await p.get_by_role("button", name="Notify me").click()
    await p.wait_for_selector("dialog[open]")
    assert await p.locator("#fp-add-rule-dialog[open]").count() == 0
    text = await p.inner_text("dialog[open]")
    assert "Tell me when Sam arrives or leaves?" in text and "Home" in text
    await p.get_by_role("button", name="Add alerts").click()
    await p.wait_for_function(
        "document.querySelector('#person-status').textContent.startsWith('Added alerts to')"
    )
    # A second tap has nothing left to add and says so, with no dialog.
    await p.get_by_role("button", name="Notify me").click()
    await p.get_by_text("Alerts are already on.").wait_for()
    assert await p.locator("dialog[open]").count() == 0


async def test_edit_person_opens_the_person_editor_not_the_group_dialog(
    trips_page, trips_server, pid
):
    await open_person(trips_page, trips_server, pid)
    p = trips_page
    await p.get_by_role("button", name="Edit person").click()
    await p.wait_for_selector("#fp-person-dialog[open]")
    assert await p.locator("#fp-group-dialog[open]").count() == 0
    text = await p.inner_text("#fp-person-dialog")
    for gone in ("Alert when", "Cluster radius", "Stale after"):
        assert gone not in text
    assert await p.input_value("#fp-person-name") == "Sam"
    assert await p.locator("#fp-person-dialog input[name=pe-kind]").count() == 2
    await p.keyboard.press("Escape")
    await p.get_by_role("button", name="Full map").click()
    await p.wait_for_selector("#tab-latest", state="visible")
    assert await p.input_value("#fp-group-select") == str(pid)

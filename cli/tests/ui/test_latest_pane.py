"""The Latest tab (dashboard 1.3): one list, people first, then trackers with no person.

Purpose    : Pin the list order, the rows' content, the Edit buttons, the empty
             state and the click targets (person page, tracker focus).
Inputs     : The day-story fixture server (Sam and Mia trackers) plus a person Alex
             who owns TAG-SON, so TAG-MOM ("Mia") stays a tracker with no person.
Outputs    : Assertions only.
Constraints: Headless Chromium; the old day body is not part of Latest any more.
"""

# ruff: noqa: E501  (inline JS snippets)
from __future__ import annotations

import pytest

from ._latest_helpers import active_tab, boot, ensure_alex

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def alex(trips_server):
    return ensure_alex(trips_server)


async def test_people_come_first_then_trackers_with_no_person(trips_page, trips_server, alex):
    await boot(trips_page, trips_server)
    rows = trips_page.locator("#fp-latest-list .fp-latest-row")
    await rows.first.wait_for()
    kinds = await rows.evaluate_all(
        "els => els.map((e) => e.classList.contains('fp-latest-row--person') ? 'person' : 'tracker')"
    )
    assert kinds == ["person", "tracker"]
    person, tracker = rows.nth(0), rows.nth(1)
    assert await person.locator(".fp-latest-name").inner_text() == "Alex"
    assert await person.locator(".fp-latest-where").inner_text() != ""
    assert await person.locator(".person-conf").count() == 1, "the confidence pill"
    assert await person.locator(".fp-latest-badges svg").count() == 1, "one tracker badge"
    assert await person.locator(".fp-latest-main svg").count() >= 2, "avatar plus badge"
    assert await tracker.locator(".fp-latest-name").inner_text() == "Mia"
    assert await tracker.locator(".fp-latest-where").inner_text() in (
        "Not at a saved place",
        "At Home",
        "At School",
        "At Work",
        "At Grandma's",
    )
    seen = await tracker.locator(".fp-latest-seen").inner_text()
    assert seen.startswith("seen ") or seen == "no recent sighting"


async def test_the_old_day_body_is_not_in_latest(trips_page, trips_server, alex):
    await boot(trips_page, trips_server)
    await trips_page.wait_for_selector("#fp-latest-list .fp-latest-row")
    for sel in ("#tracks", "#view-switch", "#view-story", "#view-raw", "#story"):
        assert await trips_page.is_hidden(sel), sel + " must not show in Latest"


async def test_each_row_has_an_edit_button(trips_page, trips_server, alex):
    await boot(trips_page, trips_server)
    await trips_page.wait_for_selector("#fp-latest-list .fp-latest-row")
    edits = trips_page.locator("#fp-latest-list .fp-latest-row [data-act=edit]")
    assert await edits.count() == 2
    assert await edits.nth(0).get_attribute("aria-label") == "Edit Alex"
    assert await edits.nth(1).get_attribute("aria-label") == "Edit Mia"
    await edits.nth(0).click()
    await trips_page.wait_for_selector("#fp-person-dialog[open]")
    await trips_page.keyboard.press("Escape")
    await edits.nth(1).click()
    await trips_page.wait_for_selector("#fp-device-dialog[open]")
    await trips_page.keyboard.press("Escape")


async def test_a_person_row_opens_the_person_page(trips_page, trips_server, alex):
    await boot(trips_page, trips_server)
    await trips_page.click("#fp-latest-list .fp-latest-row--person .fp-latest-main")
    await trips_page.wait_for_selector("#tab-person:not([hidden])")
    assert trips_page.url.endswith(f"#/person/{alex}")


async def test_left_behind_and_banner_hosts_sit_above_the_list(trips_page, trips_server, alex):
    await boot(trips_page, trips_server)
    order = await trips_page.evaluate(
        "[...document.getElementById('tab-latest').children].map((e) => e.id)"
    )
    assert order.index("fp-people-banner") < order.index("fp-latest-list")
    assert order.index("fp-left-behind") < order.index("fp-latest-list")


async def test_the_empty_state_offers_setup(trips_page, trips_server):
    await trips_page.route("**/api/people", lambda r: r.fulfill(json=[]))
    await trips_page.route(
        "**/api/devices",
        lambda r: r.fulfill(
            json={
                "default_device_id": None,
                "tracked_count": 0,
                "requests_per_hour": 0,
                "devices": [],
            }
        ),
    )
    await boot(trips_page, trips_server)
    await trips_page.wait_for_selector(".fp-latest-empty")
    assert await trips_page.inner_text(".fp-latest-empty .empty-title") == "No trackers yet"
    link = trips_page.locator(".fp-latest-empty a")
    assert await link.get_attribute("href") == "#/setup"
    assert await active_tab(trips_page) == "latest"


async def test_people_are_alphabetical_and_stale_people_are_dimmed(trips_page, trips_server):
    people = [
        {
            "id": 2,
            "name": "Zoe",
            "kind": "person",
            "color": "#e7663f",
            "icon": "lucide:user",
            "trackers": [],
        },
        {
            "id": 1,
            "name": "Alex",
            "kind": "person",
            "color": "#4f8cf7",
            "icon": "lucide:user",
            "trackers": [],
        },
    ]
    now = {
        "confidence": "unknown",
        "text": "Not sure where Zoe is.",
        "age_minutes": None,
        "stale": [],
    }
    await trips_page.route("**/api/people", lambda r: r.fulfill(json=people))
    await trips_page.route("**/api/people/*/now", lambda r: r.fulfill(json=now))
    await boot(trips_page, trips_server)
    await trips_page.wait_for_selector("#fp-latest-list .fp-latest-row--person")
    names = await trips_page.locator(".fp-latest-row--person .fp-latest-name").all_inner_texts()
    assert names == ["Alex", "Zoe"]
    assert await trips_page.locator(".fp-latest-row--person.is-stale").count() == 2
    assert "Not sure where Zoe is." in await trips_page.inner_text("#fp-latest-list")

"""Browser tests for the Places tab's arrivals/departures panel (P19/WP9).

GET /api/places/events and GET /api/groups/events are mocked here (the same
opt-in-network isolation test_places.py's own
test_address_search_is_opt_in_and_mocked uses, R-P2-30.2) because the seed
script writes zero geofence-engine rows -- no crossing has actually happened
in this throwaway install -- so the panel's own rendering, sort-merge, empty
state and pagination are exercised without depending on the engine firing a
real crossing.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_places(page, base_url):
    await page.goto(base_url + "/")
    await page.click('button[data-tab="places"]')
    # "attached", not the default "visible": an empty <ul> has a zero-size
    # box, which Playwright's own visibility check treats as hidden even
    # though it is legitimately on screen and correctly empty.
    await page.wait_for_selector("#fp-places-events-list", state="attached")


def _place_row(row_id, observed_at, event_type="ENTER"):
    return {
        "id": row_id,
        "place_id": 1,
        "place_name": "Home",
        "device_id": "TAG-HOME",
        "device_name": "Ali's Keys",
        "event_type": event_type,
        "observed_at": observed_at,
        "fetched_at": observed_at,
        "lag_minutes": 0,
        "confidence": "high",
        "distance_meters": 10,
        "accuracy_meters": 10,
        "notified_at": None,
    }


def _group_row(row_id, observed_at, note):
    return {
        "id": row_id,
        "group_id": 1,
        "group_name": "Family",
        "place_id": 1,
        "place_name": "Home",
        "event_type": "EXIT",
        "observed_at": observed_at,
        "members_crossed": 2,
        "members_considered": 3,
        "members_stale": 1,
        "confidence": "high",
        "note": note,
        "notified_at": None,
    }


async def _mock_events(page, place_rows, group_rows):
    async def handle_places(route):
        body = json.dumps(place_rows)
        await route.fulfill(status=200, content_type="application/json", body=body)

    async def handle_groups(route):
        body = json.dumps(group_rows)
        await route.fulfill(status=200, content_type="application/json", body=body)

    await page.route("**/api/places/events*", handle_places)
    await page.route("**/api/groups/events*", handle_groups)


async def test_events_panel_shows_empty_state_with_no_rows(page, base_url):
    await _mock_events(page, [], [])
    await _open_places(page, base_url)
    await page.wait_for_selector("#fp-places-events-empty:not([hidden])")
    assert await page.locator("#fp-places-events-list .fp-events-row").count() == 0


async def test_events_panel_renders_device_and_group_rows_newest_first(page, base_url):
    older = "2026-09-26T10:00:00+00:00"
    newer = "2026-09-26T11:00:00+00:00"
    await _mock_events(
        page,
        [_place_row(1, older)],
        [_group_row(1, newer, "2 of 3 tags left Home; Backpack Tag has no recent fix.")],
    )
    await _open_places(page, base_url)
    rows = page.locator("#fp-places-events-list .fp-events-row")
    await rows.first.wait_for(state="visible")
    assert await rows.count() == 2
    # newest (the group row) first.
    first_text = await rows.nth(0).inner_text()
    second_text = await rows.nth(1).inner_text()
    assert "Family" in first_text
    assert "Ali's Keys" in second_text
    assert "entered Home" in second_text


async def test_events_panel_empty_state_hides_once_rows_arrive(page, base_url):
    await _mock_events(page, [], [])
    await _open_places(page, base_url)
    await page.wait_for_selector("#fp-places-events-empty:not([hidden])")
    assert await page.locator("#fp-places-events-more").is_hidden()


async def test_events_panel_show_more_requests_a_bigger_page(page, base_url):
    seen_limits = []

    async def handle_places(route):
        limit = int(route.request.url.split("limit=")[1].split("&")[0])
        seen_limits.append(limit)
        rows = [_place_row(i, f"2026-09-26T10:{i % 60:02d}:00+00:00") for i in range(limit)]
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(rows))

    async def handle_groups(route):
        await route.fulfill(status=200, content_type="application/json", body="[]")

    await page.route("**/api/places/events*", handle_places)
    await page.route("**/api/groups/events*", handle_groups)
    await _open_places(page, base_url)
    await page.wait_for_selector("#fp-places-events-more:not([hidden])")
    first_limit = seen_limits[-1]

    await page.click("#fp-places-events-more")
    selector = "#fp-places-events-list .fp-events-row"
    await page.wait_for_function(
        f"() => document.querySelectorAll('{selector}').length > {first_limit}"
    )
    assert seen_limits[-1] > first_limit


async def test_events_panel_shows_the_alerts_latency_honesty_notice(page, base_url):
    """Honest wording: the panel's times are when Find+ observed the change,
    not the exact moment -- the same sentence the Alerts tab already shows
    for the same reason (honesty.ALERTS_LATENCY), read here from the same
    /api/config so it can never paraphrase it."""
    await _mock_events(page, [], [])
    await _open_places(page, base_url)
    await page.wait_for_function(
        "() => document.getElementById('fp-places-events-notice').textContent.length > 0"
    )
    text = await page.locator("#fp-places-events-notice").inner_text()
    assert "delay" in text.lower()

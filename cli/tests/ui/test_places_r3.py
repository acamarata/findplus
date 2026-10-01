"""Round 3 Places tab: relative event times, event load errors, list search/sort,
the per-place facts line and the edit dialog's rule-count line.

Places made here are removed again (the live server is shared by the session).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

JSON = {"Content-Type": "application/json"}


async def _add_place(page, base_url, name, radius=100, lat=40.0, lon=-74.0):
    res = await page.request.post(
        base_url + "/api/places",
        data=json.dumps(
            {
                "name": name,
                "latitude": lat,
                "longitude": lon,
                "radius_meters": radius,
                "color": "#e7663f",
                "enter_confirmations": 1,
                "exit_confirmations": 1,
            }
        ),
        headers=JSON,
    )
    assert res.ok, await res.text()
    return (await res.json())["id"]


async def card_text(page, pid):
    return await page.locator(f'[data-place-id="{pid}"]').inner_text()


async def _drop_places(page, base_url, ids):
    for pid in ids:
        await page.request.delete(f"{base_url}/api/places/{pid}")


async def _open_places(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#map.leaflet-container")
    await page.click('button[data-tab="places"]')
    await page.wait_for_selector("#fp-places-list .fp-place-card")


def _row(minutes_ago):
    at = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "id": 1,
        "place_id": 1,
        "place_name": "Home",
        "device_id": "TAG-HOME",
        "device_name": "Ali's Keys",
        "event_type": "EXIT",
        "observed_at": at,
        "fetched_at": at,
        "lag_minutes": 0,
        "confidence": "high",
        "distance_meters": 10,
        "accuracy_meters": 10,
        "notified_at": None,
    }


async def test_events_show_relative_time_with_exact_time_on_hover(page, base_url):
    async def places(route):
        await route.fulfill(
            status=200, content_type="application/json", body=json.dumps([_row(12)])
        )

    async def groups(route):
        await route.fulfill(status=200, content_type="application/json", body="[]")

    await page.route("**/api/places/events*", places)
    await page.route("**/api/groups/events*", groups)
    await _open_places(page, base_url)
    time = page.locator("#fp-places-events-list .fp-events-time").first
    await time.wait_for(state="attached")
    assert "12 minutes ago" in await time.inner_text()
    assert await time.get_attribute("title")  # absolute time with the zone
    assert await time.get_attribute("datetime")
    row = page.locator("#fp-places-events-list .fp-events-row").first
    assert await row.get_attribute("data-kind") == "exit"


async def test_events_load_failure_shows_an_error_with_retry(page, base_url):
    calls = {"n": 0}

    async def places(route):
        calls["n"] += 1
        if calls["n"] <= 2:
            await route.fulfill(status=500, content_type="application/json", body="{}")
        else:
            await route.fulfill(status=200, content_type="application/json", body="[]")

    await page.route("**/api/places/events*", places)
    await page.route(
        "**/api/groups/events*",
        lambda r: r.fulfill(status=200, body="[]", content_type="application/json"),
    )
    await page.goto(base_url + "/")
    await page.click('button[data-tab="places"]')
    err = page.locator("#fp-places-events-list [data-pane-error]")
    await err.wait_for(state="visible")
    await err.get_by_role("button", name="Retry").click()
    await page.wait_for_selector("#fp-places-events-empty:not([hidden])")


async def test_list_search_and_sort(page, base_url):
    ids = [
        await _add_place(page, base_url, "Zebra Cafe", radius=300, lat=40.0),
        await _add_place(page, base_url, "Alpha Gym", radius=50, lat=40.1),
    ]
    try:
        await _open_places(page, base_url)
        tools = page.locator(".fp-places-tools")
        await tools.wait_for(state="visible")
        names = page.locator("#fp-places-list .fp-card-name")
        mine = ["Alpha Gym", "Zebra Cafe"]
        assert [n for n in await names.all_inner_texts() if n in mine] == mine  # A to Z
        await page.select_option("#fp-places-sort", "radius")
        order = [n for n in await names.all_inner_texts() if n in mine]
        assert order == ["Zebra Cafe", "Alpha Gym"]  # 300 m before 50 m
        await page.fill("#fp-places-search", "zeb")
        assert await names.all_inner_texts() == ["Zebra Cafe"]
        # typing never loses focus (the toolbar node is kept between renders)
        assert await page.evaluate("document.activeElement.id") == "fp-places-search"
        await page.fill("#fp-places-search", "nothing like this")
        assert await names.count() == 0
        assert (
            "nothing like this"
            in await page.locator("#fp-places-list .fp-empty-state").inner_text()
        )
    finally:
        await _drop_places(page, base_url, ids)


async def test_card_shows_coordinates_and_rule_count(page, base_url):
    pid = await _add_place(page, base_url, "Facts Place", radius=120, lat=40.5, lon=-74.25)
    try:
        await _open_places(page, base_url)
        meta = page.locator(f'[data-place-id="{pid}"] .fp-place-card-meta')
        text = await meta.inner_text()
        assert "120 m radius" in text and "40.5000, -74.2500" in text
        assert "Not notifying anyone yet" in await card_text(page, pid)
    finally:
        await _drop_places(page, base_url, [pid])


async def test_edit_dialog_says_how_many_rules_use_the_place(page, base_url):
    await page.request.put(
        base_url + "/api/alerts/channels/webhook",
        data=json.dumps({"url": "http://127.0.0.1:9/hook"}),
        headers=JSON,
    )
    pid = await _add_place(page, base_url, "Rule Place")
    rule = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps(
            {"name": "R3 usage", "device_id": "TAG-HOME", "place_id": pid, "channels": ["webhook"]}
        ),
        headers=JSON,
    )
    assert rule.ok, await rule.text()
    rid = (await rule.json())["id"]
    try:
        await _open_places(page, base_url)
        card = page.locator(f'[data-place-id="{pid}"]')
        assert "1 alert rule" in await card.locator(".fp-place-card-meta").inner_text()
        await card.locator(".fp-card-edit").click()
        usage = page.locator("#fp-place-usage")
        await usage.wait_for(state="visible")
        assert "1 alert rule uses this place" in await usage.inner_text()
        await page.click("#fp-place-dialog .btn-secondary")
        # a fresh Add dialog never carries the line over
        await page.click("#fp-add-place-btn")
        await page.wait_for_selector("#fp-place-dialog[open]")
        assert await page.locator("#fp-place-usage").is_hidden()
    finally:
        await page.request.delete(f"{base_url}/api/alerts/rules/{rid}")
        await _drop_places(page, base_url, [pid])
        await page.request.delete(base_url + "/api/alerts/channels/webhook")


async def test_radius_hint_is_attached_to_the_slider(page, base_url):
    await _open_places(page, base_url)
    await page.click("#fp-add-place-btn")
    await page.wait_for_selector("#fp-place-dialog[open]")
    assert (
        await page.get_attribute("#fp-place-radius", "aria-describedby") == "fp-place-radius-hint"
    )
    assert "Find Hub" in await page.locator("#fp-place-radius-hint").inner_text()


async def test_small_radius_says_why_it_is_a_poor_choice(page, base_url):
    await _open_places(page, base_url)
    await page.click("#fp-add-place-btn")
    await page.wait_for_selector("#fp-place-dialog[open]")
    warn = page.locator("#fp-place-radius-warn")
    assert await warn.is_hidden()  # the default is 200 m
    await page.fill("#fp-place-radius-number", "60")
    await warn.wait_for(state="visible")
    text = await warn.inner_text()
    assert "Under 100 m" in text and "late" in text
    await page.fill("#fp-place-radius-number", "150")
    assert await warn.is_hidden()


async def test_ui_and_engine_agree_on_the_recommended_minimum_radius():
    import re
    from pathlib import Path

    from findplus.places.geofence import RECOMMENDED_MIN_RADIUS_METERS

    dom = Path(__file__).resolve().parents[3] / "web" / "app" / "places_dialog_dom.js"
    match = re.search(r"RECOMMENDED_MIN_RADIUS = (\d+);", dom.read_text(encoding="utf-8"))
    assert match and int(match.group(1)) == RECOMMENDED_MIN_RADIUS_METERS

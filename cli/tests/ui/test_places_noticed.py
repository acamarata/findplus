"""Browser tests for "We noticed these places": the Places tab and the wizard step."""

from __future__ import annotations

import json

import pytest

from ._noticed_helpers import GRANDMA, HOME, SCHOOL, payload, serve
from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _open_places(page, base_url):
    await page.goto(base_url + "/")
    await page.click('button[data-tab="places"]')
    await page.wait_for_selector("#fp-places-noticed .pn-card")


async def test_cards_show_home_first_with_plain_facts_and_a_mini_map(page, base_url):
    await serve(page)
    await _open_places(page, base_url)
    titles = await page.locator("#fp-places-noticed .pn-title").all_inner_texts()
    assert titles == ["Home?", "School or work?", "Regular stop"]
    school = await page.locator("#fp-places-noticed .pn-card").nth(1).inner_text()
    assert "15 visits on 15 days" in school and "8:10 AM to 3:00 PM on weekdays" in school
    home = await page.locator("#fp-places-noticed .pn-card").first.inner_text()
    assert "20 nights there" in home and "Seen by Kai, Mia" in home
    await page.wait_for_function(
        "() => document.querySelectorAll('#fp-places-noticed .pn-map.leaflet-container').length"
        " === 3"
    )


async def test_no_names_are_invented(page, base_url):
    await serve(page)
    await _open_places(page, base_url)
    assert await page.locator("#fp-places-noticed input[type=text]").count() == 0


async def test_name_it_saves_with_the_spots_own_numbers_and_the_notify_box(page, base_url):
    _, created = await serve(page)
    await _open_places(page, base_url)
    card = page.locator("#fp-places-noticed .pn-card").first
    await card.get_by_role("button", name="Name it").click()
    assert await card.locator("select").input_value() == "home"
    assert await card.locator("input[type=checkbox]").is_checked()
    await card.locator("input[type=text]").fill("Our House")
    await card.get_by_role("button", name="Save place").click()
    await page.wait_for_selector(".pn-saved")
    assert created == [
        {
            "name": "Our House",
            "latitude": HOME["lat"],
            "longitude": HOME["lon"],
            "radius_meters": 100,
            "kind": "home",
            "notify": True,
        }
    ]
    assert await page.locator("#fp-places-noticed .pn-card").count() == 2
    assert "Saved Our House." in await page.locator(".pn-saved").inner_text()


async def test_the_kind_follows_the_name_until_picked(page, base_url):
    await serve(page)
    await _open_places(page, base_url)
    card = page.locator("#fp-places-noticed .pn-card").nth(2)
    await card.get_by_role("button", name="Name it").click()
    await card.locator("input[type=text]").fill("Grandma's")
    assert await card.locator("select").input_value() == "family"
    await card.locator("select").select_option("shop")
    await card.locator("input[type=text]").fill("Grandma's House")
    assert await card.locator("select").input_value() == "shop"


async def test_not_a_place_is_remembered_and_the_card_goes(page, base_url):
    dismissed, _ = await serve(page)
    await _open_places(page, base_url)
    await (
        page.locator("#fp-places-noticed .pn-card")
        .nth(2)
        .get_by_role("button", name="Not a place")
        .click()
    )
    await page.wait_for_function(
        "() => document.querySelectorAll('#fp-places-noticed .pn-card').length === 2"
    )
    assert dismissed == [{"latitude": GRANDMA["lat"], "longitude": GRANDMA["lon"]}]


async def test_nothing_is_saved_without_a_click(page, base_url):
    _, created = await serve(page)
    await _open_places(page, base_url)
    await (
        page.locator("#fp-places-noticed .pn-card")
        .first.get_by_role("button", name="Name it")
        .click()
    )
    await page.get_by_role("button", name="Cancel").first.click()
    assert created == []
    assert await page.locator("#fp-places-noticed .pn-card").count() == 3


async def _open_step(page, base_url):
    await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": None}),
        headers={"Content-Type": "application/json"},
    )
    await page.request.post(
        base_url + "/api/settings/onboarding.last_step",
        data=json.dumps({"value": "places"}),
        headers={"Content-Type": "application/json"},
    )
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)


async def _restore(page, base_url):
    await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": SEEDED_COMPLETED_AT}),
        headers={"Content-Type": "application/json"},
    )


async def test_wizard_step_shows_the_cards(page, base_url):
    await serve(page, payload(HOME, SCHOOL))
    try:
        await _open_step(page, base_url)
        await page.wait_for_selector("#fp-setup-places-noticed .pn-card")
        titles = await page.locator("#fp-setup-places-noticed .pn-title").all_inner_texts()
        assert titles == ["Home?", "School or work?"]
    finally:
        await _restore(page, base_url)


async def test_wizard_step_explains_when_there_is_too_little_history(page, base_url):
    await serve(page, {"candidates": []})

    async def no_places(route):
        if route.request.method == "GET":
            await route.fulfill(json=[])
        else:
            await route.fallback()

    await page.route("**/api/places", no_places)
    try:
        await _open_step(page, base_url)
        await page.wait_for_selector("#fp-setup-places-noticed .pn-empty")
        text = await page.locator("#fp-setup-places-noticed .pn-empty").inner_text()
        assert text == "Find+ needs a few days of sightings to suggest places."
    finally:
        await _restore(page, base_url)


async def test_wizard_map_shows_one_pin_for_trackers_in_the_same_spot(page, base_url):
    """Sixteen trackers at one address used to draw sixteen stacked pins."""
    await serve(page, {"candidates": []})
    devices = [
        {
            "device_id": f"STACK-{i}",
            "name": f"Tag {i}",
            "label": None,
            "icon": "letter",
            "color": "#3b82f6",
            "is_tracked": True,
            "observation_count": 3,
        }
        for i in range(16)
    ]
    await page.route("**/api/devices", lambda r: r.fulfill(json={"devices": devices}))
    fix = {"latitude": 41.1, "longitude": -80.1, "observed_at": "2026-09-27T12:00:00Z"}
    await page.route("**/api/latest*", lambda r: r.fulfill(json=fix))
    try:
        await _open_step(page, base_url)
        await page.wait_for_selector(".marker-count")
        assert await page.locator(".marker-count").inner_text() == "16"
        assert await page.locator("#fp-setup-map-host .leaflet-marker-icon").count() == 1
    finally:
        await _restore(page, base_url)

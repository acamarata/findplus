"""The place dialog: kind, the "Tell me when anyone arrives or leaves" box, and the radius advice."""

# ruff: noqa: E501

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from ._notify_helpers import WEBHOOK, WHATSAPP, channels, delete_places, open_add_dialog

pytestmark = pytest.mark.asyncio(loop_scope="session")
NAMES = [
    "Grandma's House",
    "Home",
    "Little School",
    "Notify One",
    "Notify Pick",
    "Notify None",
    "Plain Spot",
]


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _clean(page, base_url):
    yield
    await delete_places(page, base_url, *[n for n in NAMES if n != "Home"], "Notify Two")


async def _capture_post(page):
    sent: list[dict] = []

    async def handler(route):
        if route.request.method == "POST":
            sent.append(json.loads(route.request.post_data))
        await route.continue_()

    await page.route("**/api/places", handler)
    return sent


async def test_kind_is_guessed_from_the_name_until_the_owner_picks(page, base_url):
    await open_add_dialog(page, base_url)
    kind = page.locator("#fp-place-kind")
    assert await kind.input_value() == "other"
    await page.fill("#fp-place-name", "Grandma's House")
    assert await kind.input_value() == "family"
    await page.fill("#fp-place-name", "Little School")
    assert await kind.input_value() == "school"
    await kind.select_option("shop")
    await page.fill("#fp-place-name", "Grandma's House")
    assert await kind.input_value() == "shop", "a kind the owner picked is never overwritten"


async def test_home_explains_itself(page, base_url):
    await open_add_dialog(page, base_url)
    await page.fill("#fp-place-name", "Our Home")
    assert await page.locator("#fp-place-kind").input_value() == "home"
    hint = await page.inner_text("#fp-place-kind-hint")
    assert "left-behind alerts stay off" in hint and "Overnight at Home" in hint


async def test_js_guess_matches_the_server_guess(page, base_url):
    from findplus.places.kinds import guess_place_kind

    await open_add_dialog(page, base_url)
    names = [
        "Grandma's",
        "St Mary's School",
        "Head Office",
        "Corner Shop",
        "My house",
        "Jaddah",
        "Park",
        "Naan Bakery",
        "Auntie\u2019s flat",
        "Madrasa",
        "",
    ]
    got = await page.evaluate(
        "async (names) => { const m = await import('/static/app/places_kind.js'); return names.map(m.guessKind); }",
        names,
    )
    assert got == [guess_place_kind(n) for n in names]


async def test_box_stays_ticked_and_says_the_alert_is_off_when_nothing_is_connected(
    page, base_url, ui_env
):
    with channels(ui_env):
        sent = await _capture_post(page)
        await open_add_dialog(page, base_url)
        box = page.locator("#fp-place-notify")
        assert await box.is_checked() and not await box.is_disabled()
        assert "saved but stays off until you connect Telegram, WhatsApp or a webhook" in (
            await page.inner_text("#fp-place-notify-line")
        )
        await page.fill("#fp-place-name", "Notify None")
        await page.get_by_role("button", name="Save", exact=True).click()
        await page.wait_for_function("() => !document.getElementById('fp-place-dialog').open")
        assert sent[0]["notify"] is True
        assert await page.locator("#fp-add-rule-dialog[open]").count() == 0, (
            "no second dialog by itself"
        )


async def test_one_channel_is_chosen_for_you_and_makes_the_rule_without_a_second_dialog(
    page, base_url, ui_env
):
    with channels(ui_env, webhook=WEBHOOK):
        sent = await _capture_post(page)
        await open_add_dialog(page, base_url)
        assert await page.is_checked("#fp-place-notify")
        assert "Sent to Webhook." in await page.inner_text("#fp-place-notify-line")
        assert await page.locator("#fp-place-notify-channel").is_hidden()
        await page.fill("#fp-place-name", "Notify One")
        await page.get_by_role("button", name="Save", exact=True).click()
        await page.get_by_text("Alerts are on for Notify One: Webhook.").wait_for()
        assert sent[0]["notify"] is True and "notify_channels" not in sent[0]
        assert sent[0]["kind"] == "other"
        assert await page.locator("#fp-add-rule-dialog[open]").count() == 0
        rules = await (await page.request.get(base_url + "/api/alerts/rules")).json()
        mine = [r for r in rules if r["place_name"] == "Notify One"]
        assert len(mine) == 1 and mine[0]["all_people"] and mine[0]["channels"] == ["webhook"]
        await page.get_by_role("button", name="Customise").click()
        await page.wait_for_selector('#fp-add-rule-dialog[data-fp-ready="true"]')
        intro = await page.locator("#fp-rule-intro").inner_text()
        assert "Notify One already sends a message" in intro
        assert await page.locator("#fp-rule-place option:checked").inner_text() == "Notify One"


async def test_several_channels_offer_a_select_and_send_the_pick(page, base_url, ui_env):
    with channels(ui_env, webhook=WEBHOOK, whatsapp=WHATSAPP):
        sent = await _capture_post(page)
        await open_add_dialog(page, base_url)
        select = page.locator("#fp-place-notify-channel")
        assert await select.is_visible()
        options = await select.locator("option").all_inner_texts()
        assert options[-1] == "Every connected channel" and len(options) == 3
        await select.select_option("whatsapp")
        await page.fill("#fp-place-name", "Notify Pick")
        await page.get_by_role("button", name="Save", exact=True).click()
        await page.get_by_text("Alerts are on for Notify Pick: WhatsApp.").wait_for()
        assert sent[0]["notify_channels"] == ["whatsapp"]


async def test_unticking_the_box_saves_no_rule(page, base_url, ui_env):
    with channels(ui_env, webhook=WEBHOOK):
        sent = await _capture_post(page)
        await open_add_dialog(page, base_url)
        await page.uncheck("#fp-place-notify")
        await page.fill("#fp-place-name", "Plain Spot")
        await page.get_by_role("button", name="Save", exact=True).click()
        card = page.locator(".fp-place-card", has_text="Plain Spot")
        await card.wait_for()
        assert sent[0]["notify"] is False
        assert "Not notifying anyone yet" in await card.inner_text()
        assert await page.locator("#fp-add-rule-dialog[open]").count() == 0
        await card.get_by_role("button", name="Set up an alert").click()
        await page.wait_for_selector('#fp-add-rule-dialog[data-fp-ready="true"]')
        assert "Plain Spot is saved" in await page.locator("#fp-rule-intro").inner_text()
        assert await page.locator("#fp-rule-place option:checked").inner_text() == "Plain Spot"
        await page.click("#fp-rule-cancel")


async def test_editing_a_place_hides_the_box_and_shows_its_kind(page, base_url):
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready]")
    await page.click('button[data-tab="places"]')
    card = page.locator(".fp-place-card", has_text="Home").first
    await card.get_by_role("button", name="Edit").click()
    await page.wait_for_selector("#fp-place-dialog[open]")
    assert await page.locator(".fp-notify").is_hidden()
    assert await page.locator("#fp-place-kind").input_value() in ("home", "other")


async def test_radius_advice_is_visible_with_its_reason(page, base_url):
    await open_add_dialog(page, base_url)
    assert "Recommended: 100 m or more" in await page.inner_text("#fp-place-radius-hint")
    await page.locator("#fp-place-radius-number").fill("60")
    text = await page.inner_text("#fp-place-radius-warn")
    assert "Under 100 m" in text and "alerts for this place may be missed" in text

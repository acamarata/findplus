"""Wizard 1.3 (U16, U30, U38): Google leads, the people step is people first, the
close control is an icon button."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

SEEDED = "2026-01-01T00:00:00+00:00"


async def _post(page, base_url, key, value):
    await page.request.post(
        f"{base_url}/api/settings/{key}",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _unfinished(page, base_url):
    await _post(page, base_url, "onboarding.completed_at", None)
    try:
        yield
    finally:
        await _post(page, base_url, "onboarding.completed_at", SEEDED)
        await _post(page, base_url, "onboarding.last_step", None)


async def _open(page, base_url, step):
    await _post(page, base_url, "onboarding.last_step", step)
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step h2", timeout=15000)


async def test_google_is_the_primary_sign_in_and_apple_is_secondary(page, base_url):
    await _open(page, base_url, "signin")
    google = page.locator("#fp-setup-google-hello")
    apple = page.locator("#fp-setup-apple-signin")
    await google.wait_for(state="visible")
    await apple.wait_for(state="visible")
    g = await google.evaluate("e => getComputedStyle(e).backgroundColor")
    a = await apple.evaluate("e => getComputedStyle(e).backgroundColor")
    accent = await page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()"
    )
    assert g != a, "the two buttons must not carry the same emphasis"
    probe = await page.evaluate(
        "(c) => { const d = document.createElement('i'); d.style.color = c;"
        " document.body.append(d); const v = getComputedStyle(d).color; d.remove(); return v; }",
        accent,
    )
    assert g == probe, "Google wears the accent colour"


async def test_a_held_next_names_its_reason(page, base_url):
    await _open(page, base_url, "signin")
    next_btn = page.locator("#fp-wizard-next")
    await next_btn.wait_for(state="visible")
    if await next_btn.is_disabled():
        assert await next_btn.get_attribute("aria-describedby") == "fp-setup-signin-next-hint"
        assert "Connect at least one account" in await page.inner_text("#fp-setup-signin-next-hint")


async def test_close_is_a_32px_icon_button_with_a_name(page, base_url):
    await _open(page, base_url, "signin")
    close = page.locator("#fp-wizard-skip-all")
    assert await close.get_attribute("aria-label") == "Skip setup"
    assert (await close.inner_text()).strip() == ""
    box = await close.bounding_box()
    assert box["width"] >= 32 and box["height"] >= 32


async def test_the_people_step_hides_the_group_form_until_asked(page, base_url):
    await _open(page, base_url, "groups")
    await page.wait_for_selector("#fp-setup-person-name")
    assert await page.locator("#fp-setup-person-add").is_visible()
    assert await page.locator("#fp-setup-group-name").is_hidden()
    await page.click("#fp-setup-groups-more > summary")
    assert await page.locator("#fp-setup-group-name").is_visible()
    assert (
        await page.inner_text("#fp-setup-groups-more > summary")
    ).strip() == "Add a group instead"


async def test_add_a_person_needs_a_name_and_a_tracker_then_posts(page, base_url):
    posts = []

    async def handler(route):
        if route.request.method == "POST":
            posts.append(json.loads(route.request.post_data))
            await route.fulfill(status=201, content_type="application/json", body="{}")
        else:
            await route.continue_()

    await page.route("**/api/people", handler)
    await _open(page, base_url, "groups")
    await page.wait_for_selector("#fp-setup-person-name")
    await page.click("#fp-setup-person-add-btn")
    assert "Name is required." in await page.inner_text("#fp-setup-person-error")
    await page.fill("#fp-setup-person-name", "Sam")
    await page.click("#fp-setup-person-add-btn")
    assert "Select at least one member." in await page.inner_text("#fp-setup-person-error")
    await page.locator(
        "#fp-setup-person-members input[data-device-id]:not([disabled])"
    ).first.check()
    await page.click("#fp-setup-person-add-btn")
    await page.get_by_text("Added Sam.").wait_for()
    assert posts[0]["name"] == "Sam" and posts[0]["kind"] == "person" and posts[0]["member_ids"]

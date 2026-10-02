"""Round 3 wizard behaviour: progress, focus, drafts, honest step copy, re-run.

Purpose    : Pins what the setup wizard promises a first-time user: an accurate
             and accessible progress group, focus on the new step's heading,
             typed values that survive Back and Skip, a Devices step that says
             what tracking costs, a locked-Google hint, a summary that states
             what Find+ is doing and where to find it, and a re-run from
             Settings that cannot undo or re-stamp anything.
Constraints: Auth, devices and lock-status routes are stubbed; nothing real is
             contacted. onboarding.* is restored after every test.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from ._signin_helpers import reply, status_body
from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")

DEVICES = [
    {
        "device_id": f"d{i}",
        "name": f"Tag {i}",
        "label": None,
        "icon": "letter",
        "color": None,
        "provider": "google-find-hub",
        "is_tracked": i < 2,
    }
    for i in range(3)
]


async def _post(page, base_url, key, value):
    await page.request.post(
        f"{base_url}/api/settings/{key}",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _unfinished(page, base_url):
    await _post(page, base_url, "onboarding.completed_at", None)
    await _post(page, base_url, "onboarding.last_step", None)
    try:
        yield
    finally:
        await _post(page, base_url, "onboarding.completed_at", SEEDED_COMPLETED_AT)
        await _post(page, base_url, "onboarding.last_step", None)


async def _open(page, base_url, step):
    await _post(page, base_url, "onboarding.last_step", step)
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step h2", timeout=15000)


async def _stub_devices(page, devices=DEVICES, tracked=2):
    async def handler(route):
        if route.request.method == "GET":
            await route.fulfill(json={"devices": devices, "tracked_count": tracked})
        else:
            await route.fulfill(json={})

    await page.route("**/api/devices", handler)
    await page.route("**/api/devices/refresh", reply({}))


async def test_progress_is_a_named_group_not_a_live_region(page, base_url):
    await page.route("**/api/auth/status", reply(status_body()))
    await _open(page, base_url, "signin")
    progress = page.locator(".fp-wizard-progress")
    assert await progress.get_attribute("role") == "group"
    assert await progress.get_attribute("aria-live") is None
    assert await progress.get_attribute("aria-label") == "Step 2 of 8: Connect your accounts"
    dots = page.locator(".fp-wizard-dot")
    assert await dots.count() == 8
    assert await dots.first.get_attribute("aria-hidden") == "true"


async def test_a_new_step_puts_focus_on_its_heading(page, base_url):
    await _open(page, base_url, "welcome")
    await page.click("#fp-wizard-next")
    await page.wait_for_selector("#fp-setup-signin-status", timeout=15000)
    focused = await page.evaluate(
        "() => ({tag: document.activeElement.tagName, text: document.activeElement.textContent})"
    )
    assert focused == {"tag": "H2", "text": "Connect your accounts"}


async def test_welcome_leads_with_purpose_and_a_start_button(page, base_url):
    await _open(page, base_url, "welcome")
    text = await page.locator("#setup-view .fp-wizard-step").inner_text()
    assert "privately" in await page.locator("#setup-view h2").first.text_content()
    assert "every other step is optional" in text
    assert (await page.locator("#fp-wizard-next").inner_text()).strip() == "Get started"
    assert await page.locator(".fp-wizard-rerun").count() == 0


async def test_group_name_survives_back_and_skip(page, base_url):
    await _stub_devices(page)
    await _open(page, base_url, "groups")
    await page.fill("#fp-setup-group-name", "Road trip")
    await page.click("#fp-wizard-back")
    await page.wait_for_selector("#fp-setup-devices-list", timeout=15000)
    await page.click("#fp-wizard-skip")
    await page.wait_for_selector("#fp-setup-group-name", timeout=15000)
    assert await page.input_value("#fp-setup-group-name") == "Road trip"


async def test_typed_pin_survives_back_and_is_gone_after_the_wizard_closes(page, base_url):
    await _open(page, base_url, "applock")
    await page.fill("#fp-setup-pin", "123456")
    await page.fill("#fp-setup-pin-confirm", "123456")
    await page.click("#fp-wizard-back")
    await page.wait_for_selector("#fp-setup-pin", state="detached", timeout=15000)
    await page.click("#fp-wizard-skip")
    await page.wait_for_selector("#fp-setup-pin", timeout=15000)
    assert await page.input_value("#fp-setup-pin") == "123456"
    await page.evaluate(
        "async () => { const l = await import('/static/app/lock.js');"
        " await l.purgeRenderedData(); }"
    )
    assert (await page.locator("#setup-view").inner_text()).strip() == ""


async def test_devices_step_explains_cost_and_counts_the_selection(page, base_url):
    await page.route("**/api/auth/status", reply(status_body(google=True)))
    await _stub_devices(page)
    await _open(page, base_url, "devices")
    await page.wait_for_selector("#fp-setup-devices-list [data-track]", timeout=15000)
    text = await page.locator("#setup-view .fp-wizard-step").inner_text()
    assert "more polling" in text
    assert "never show a location" in text
    count = page.locator("#fp-setup-devices-count")
    assert (await count.inner_text()) == "2 of 3 selected"
    await page.locator("[data-track]").first.uncheck()
    assert (await count.inner_text()) == "1 of 3 selected"


async def test_devices_signed_out_offers_a_way_back_to_sign_in(page, base_url):
    await page.route("**/api/auth/status", reply(status_body()))
    await _stub_devices(page, devices=[], tracked=0)
    await _open(page, base_url, "devices")
    button = page.get_by_role("button", name="Back to sign-in")
    await button.wait_for(state="visible", timeout=15000)
    assert "no account is connected" in await page.locator("#fp-setup-devices-list").inner_text()
    # The empty state already says why; the red error line stays quiet on arrival.
    assert (await page.locator("#fp-setup-devices-error").inner_text()) == ""
    await button.click()
    await page.wait_for_selector("#fp-setup-signin-status", timeout=15000)


async def test_signin_says_when_google_is_connected_but_locked(page, base_url):
    await page.route("**/api/auth/status", reply(status_body(google=True, needs_g=["shared_key"])))
    await _open(page, base_url, "signin")
    await page.wait_for_function(
        "() => document.getElementById('fp-setup-signin-status')"
        ".textContent.includes('still locked')",
        timeout=15000,
    )


async def test_done_states_what_find_is_doing_and_where_to_find_it(page, base_url):
    await page.route("**/api/auth/status", reply(status_body(google=True)))
    await page.route("**/api/devices", reply({"devices": DEVICES, "tracked_count": 2}))
    await page.route(
        "**/api/lock/status",
        reply({"lock_configured": False, "lock_enabled": False, "locked": False}),
    )
    await _open(page, base_url, "done")
    await page.wait_for_selector("#setup-view p[data-ready='true']", timeout=15000)
    facts = await page.locator("#fp-setup-done-facts").inner_text()
    assert "Connected: g@example.com" in facts
    assert "about every" in facts and "minutes" in facts
    assert "App lock is off." in facts
    step = await page.locator("#setup-view .fp-wizard-step").inner_text()
    assert "Where to find things" in step
    assert base_url in step
    assert "Run setup again" in step


async def test_rerun_close_keeps_the_original_completed_date(page, base_url):
    await _post(page, base_url, "onboarding.completed_at", SEEDED_COMPLETED_AT)
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)
    assert await page.locator(".fp-wizard-rerun").is_visible()
    button = page.locator("#fp-wizard-skip-all")
    assert (await button.inner_text()).strip() == "Close setup"
    await button.click()
    await page.wait_for_function(
        "() => document.getElementById('setup-view').hidden === true", timeout=15000
    )
    settings = await (await page.request.get(base_url + "/api/settings")).json()
    assert settings["onboarding.completed_at"] == SEEDED_COMPLETED_AT


async def test_app_lock_step_does_not_offer_a_second_pin_when_one_exists(page, base_url):
    calls = []

    async def pin(route):
        calls.append(route.request.url)
        await route.abort()

    await page.route("**/api/settings/pin", pin)
    await page.route(
        "**/api/lock/status",
        reply({"lock_configured": True, "lock_enabled": True, "locked": False}),
    )
    await _open(page, base_url, "applock")
    await page.wait_for_selector("#fp-setup-pin-already", state="visible", timeout=15000)
    assert await page.locator("#fp-setup-pin").is_hidden()
    await page.click("#fp-wizard-next")
    await page.wait_for_selector("#setup-view p[data-ready]", timeout=15000)
    assert calls == []


async def test_offline_line_appears_and_clears(page, base_url):
    await _open(page, base_url, "welcome")
    assert await page.locator("#fp-wizard-offline").inner_text() == ""
    await page.context.set_offline(True)
    await page.evaluate("() => window.dispatchEvent(new Event('offline'))")
    try:
        await page.wait_for_function(
            "() => document.getElementById('fp-wizard-offline').textContent.includes('offline')",
            timeout=5000,
        )
    finally:
        await page.context.set_offline(False)
    await page.evaluate("() => window.dispatchEvent(new Event('online'))")
    await page.wait_for_function(
        "() => document.getElementById('fp-wizard-offline').textContent === ''", timeout=5000
    )


@pytest.mark.parametrize("step", ["welcome", "signin", "devices", "applock", "done"])
async def test_phone_width_has_no_sideways_scroll_and_thumb_sized_buttons(page, base_url, step):
    await page.set_viewport_size({"width": 375, "height": 812})
    await page.route("**/api/auth/status", reply(status_body(google=True, apple=True)))
    await _stub_devices(page)
    await _open(page, base_url, step)
    await page.wait_for_timeout(600)
    overflow = await page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 0, overflow
    box = await page.locator("#fp-wizard-next").bounding_box()
    assert box["height"] >= 44, box

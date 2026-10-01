"""The dashboard banner for a locked account, a poll under way, and a quiet poll.

Purpose    : The first real sign-in showed "locations are encrypted and not
             unlocked yet" with a button to the generic sign-in, said nothing
             while the poll ran, and said nothing when it found no new
             locations. Each now has its own plain-words banner:
             (1) needs_shared_key -> "Unlock locations", straight to the
                 Google unlock step, keyboard operable;
             (3) "Polling N trackers..." while a poll is expected or running;
             (3) a cycle with nothing new says why, and "no recent sighting"
                 is information (blue), never a failure.
Constraints: /api/status and /api/auth/status are stubbed; no Chrome launch.
"""

from __future__ import annotations

import pytest

from ._live_helpers import (
    feed_for,
    open_dashboard,
    reload_status,
    stub_google_locked,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

LOCKED = {t: ("needs_shared_key", 0) for t in ("TAG-HOME", "TAG-AWAY", "TAG-STALE")}
UNLOCK_BTN = "#fp-auth-google-unlock-btn"


async def test_a_locked_poll_offers_unlock_locations_not_generic_sign_in(page, base_url):
    await stub_google_locked(page)
    feed = await feed_for(page, base_url)
    feed.cycle(LOCKED, 200)
    await open_dashboard(page, base_url)

    action = page.locator("#alert .alert-action")
    await action.wait_for(state="visible")
    assert (await action.inner_text()) == "Unlock locations"
    assert "encrypted" in await page.inner_text("#alert .alert-text")

    await action.click()
    await page.wait_for_selector("#settings-modal:not(.hidden)")
    block = page.locator("#fp-auth-google-unlock")
    await block.wait_for(state="visible", timeout=10000)
    # Straight to the step: its button gets focus and is on screen.
    await page.wait_for_function(
        "() => document.activeElement && document.activeElement.id === 'fp-auth-google-unlock-btn'"
    )
    assert await page.locator(UNLOCK_BTN).is_visible()
    assert await page.locator(UNLOCK_BTN).evaluate(
        "(el) => { const r = el.getBoundingClientRect();"
        " return r.top >= 0 && r.bottom <= innerHeight; }"
    )


async def test_the_unlock_action_works_from_the_keyboard(page, base_url):
    await stub_google_locked(page)
    feed = await feed_for(page, base_url)
    feed.cycle(LOCKED, 210)
    await open_dashboard(page, base_url)

    action = page.locator("#alert .alert-action")
    await action.wait_for(state="visible")
    await action.focus()
    await page.keyboard.press("Enter")
    await page.wait_for_selector("#settings-modal:not(.hidden)")
    await page.locator("#fp-auth-google-unlock").wait_for(state="visible", timeout=10000)


async def test_a_signed_out_poll_still_offers_connect_an_account(page, base_url):
    feed = await feed_for(page, base_url)
    feed.cycle({t: ("provider_unauthenticated", 0) for t in LOCKED}, 220)
    await open_dashboard(page, base_url)
    action = page.locator("#alert .alert-action")
    await action.wait_for(state="visible")
    assert (await action.inner_text()) == "Connect an account"


async def test_one_locked_tracker_among_healthy_ones_still_says_locked(page, base_url):
    """The newest run alone used to decide the banner; a locked account shows
    on every device's own run, so any of them is enough."""
    feed = await feed_for(page, base_url)
    feed.cycle(
        {"TAG-HOME": ("ok", 1), "TAG-AWAY": ("needs_shared_key", 0), "TAG-STALE": ("ok", 0)}, 230
    )
    await open_dashboard(page, base_url)
    action = page.locator("#alert .alert-action")
    await action.wait_for(state="visible")
    assert (await action.inner_text()) == "Unlock locations"


async def test_an_expected_poll_shows_polling_n_trackers_with_a_spinner(page, base_url):
    await stub_google_locked(page, locked=False)
    feed = await feed_for(page, base_url)
    feed.cycle(LOCKED, 240)
    await open_dashboard(page, base_url)
    await page.locator("#alert .alert-action").wait_for(state="visible")

    # The unlock finished: the sign-in panel announces it, the next poll is due.
    await page.evaluate("() => window.dispatchEvent(new CustomEvent('findplus:accounts-changed'))")
    alert = page.locator("#alert.info")
    await alert.wait_for(state="visible", timeout=10000)
    assert "Polling 3 trackers" in await alert.inner_text()
    assert await page.locator("#alert .alert-spinner").count() == 1
    assert await page.get_attribute("#alert", "role") == "status"

    # The poll lands: the banner moves on to the result by itself.
    feed.cycle({"TAG-HOME": ("ok", 2), "TAG-AWAY": ("ok", 1), "TAG-STALE": ("ok", 0)}, 250)
    await page.wait_for_function(
        "() => !document.getElementById('alert').textContent.includes('Polling')", timeout=15000
    )


async def test_poll_now_says_polling_while_the_request_runs(page, base_url):
    feed = await feed_for(page, base_url)
    feed.cycle({t: ("ok", 0) for t in LOCKED}, 260)
    release = []

    async def slow_poll(route):
        while not release:
            await page.wait_for_timeout(50)
        await route.fulfill(json={"devices_polled": 3, "observations_new": 0, "results": []})

    await page.route("**/api/poll-now", slow_poll)
    await open_dashboard(page, base_url)
    await page.click("#btn-poll")
    await page.wait_for_function(
        "() => document.getElementById('alert').textContent.includes('Polling 3 trackers')"
    )
    await reload_status(page)  # a status refresh mid-request keeps saying it
    assert "Polling 3 trackers" in await page.inner_text("#alert")
    release.append(1)
    await page.wait_for_function(
        "() => !document.getElementById('alert').textContent.includes('Polling')", timeout=15000
    )


async def test_no_new_locations_after_a_poll_says_why_in_plain_words(page, base_url):
    feed = await feed_for(page, base_url)
    silent = {t: ("no_location", 0) for t in LOCKED}
    feed.cycle(silent, 270, observations_today=0, observations_total=0)
    await open_dashboard(page, base_url)
    alert = page.locator("#alert.info")
    await alert.wait_for(state="visible")
    text = await alert.inner_text()
    assert "no new locations" in text and "no recent sighting" in text.lower()
    assert "3 trackers" in text
    assert await page.locator("#alert.warn, #alert:not(.info)").count() == 0
    assert "failed" not in text.lower() and "error" not in text.lower()
    # The card line carries the same fact, and the dot is not amber.
    assert await page.inner_text("#card-poll-status") == "last attempt: no recent sighting"
    assert await page.get_attribute("#live-dot", "data-health") != "warn"


async def test_some_trackers_without_a_sighting_are_named(page, base_url):
    feed = await feed_for(page, base_url)
    feed.cycle(
        {"TAG-HOME": ("ok", 0), "TAG-AWAY": ("no_location", 0), "TAG-STALE": ("no_location", 0)},
        280,
        observations_today=0,
        observations_total=0,
    )
    await open_dashboard(page, base_url)
    text = await page.locator("#alert.info").inner_text()
    assert "No recent sighting: " in text
    assert "Away Tag" in text and "Stale Tag" in text and "Ali's Keys" not in text
    assert "Find Hub sent no newer locations" in text and "same place" not in text
    card = await page.inner_text("#card-poll-status")
    assert card == "last attempt: worked · 2 trackers with no recent sighting"

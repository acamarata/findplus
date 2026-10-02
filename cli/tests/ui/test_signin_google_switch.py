""" "Switch Google account" through the helper waits for the NEW sign-in.

Purpose    : when Google is already signed in, the first status poll is
             signed-in too. The card must keep waiting until the sign-in
             generation moves past the one the click began with, then show the
             new account. No real browser: begin and status are stubbed.
"""

from __future__ import annotations

import pytest

from ._signin_helpers import status_body, wait_text

pytestmark = pytest.mark.asyncio(loop_scope="session")

HELLO_STATUS = "#fp-auth-google-hello-status"


async def test_switch_account_keeps_waiting_until_the_generation_advances(page, base_url):
    state = {"generation": 3, "account": "old@example.com"}

    def body() -> dict:
        out = status_body(google=True)
        out["providers"][0]["account"] = state["account"]
        out["google_signin_generation"] = state["generation"]
        return out

    async def status_route(route):
        await route.fulfill(json=body())

    async def begin_route(route):
        await route.fulfill(json={"browser": "chrome", "generation": state["generation"]})

    await page.add_init_script("window.__FP_TEST_STATUS_POLL_MS__ = 40;")
    await page.route("**/api/auth/status", status_route)
    await page.route("**/api/auth/google/helper/begin", begin_route)
    await page.goto(base_url + "/#dashboard")
    await page.click("#btn-settings")
    await wait_text(page, "#fp-auth-google-status", "old@example.com")

    await page.get_by_role("button", name="Switch Google account").click()
    await wait_text(page, HELLO_STATUS, "Finish signing in")
    await page.wait_for_timeout(400)  # many polls, all still the old sign-in
    assert await page.locator(HELLO_STATUS).is_visible()
    assert "old@example.com" in await page.locator("#fp-auth-google-status").inner_text()

    state.update(generation=4, account="new@example.com")
    await wait_text(page, "#fp-auth-google-status", "new@example.com")
    assert not await page.locator(HELLO_STATUS).is_visible()


async def test_a_failed_hand_off_shows_a_plain_error_on_the_card(page, base_url):
    outcome = {"v": None}

    def body() -> dict:
        out = status_body()
        out["google_signin_generation"] = 0
        out["google_helper_outcome"] = outcome["v"]
        return out

    async def status_route(route):
        await route.fulfill(json=body())

    async def begin_route(route):
        outcome["v"] = {"kind": "signin", "ok": False, "message": "Couldn't reach Google."}
        await route.fulfill(json={"browser": "chrome", "generation": 0})

    await page.add_init_script("window.__FP_TEST_STATUS_POLL_MS__ = 40;")
    await page.route("**/api/auth/status", status_route)
    await page.route("**/api/auth/google/helper/begin", begin_route)
    await page.goto(base_url + "/#dashboard")
    await page.click("#btn-settings")
    await page.wait_for_selector("#fp-auth-google-status:not(:empty)", timeout=15000)
    await page.get_by_role("button", name="Sign in with Google").click()
    await wait_text(page, "#fp-auth-google-hello-error", "Couldn't reach Google.")
    assert (
        await page.locator("#fp-auth-google-hello-error")
        .get_by_role("button", name="Try again")
        .is_visible()
    )

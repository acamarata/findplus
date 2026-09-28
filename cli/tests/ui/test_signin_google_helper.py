"""The primary "Sign in with Google" button (the Chrome-helper flow).

Purpose    : the neutral primary button posts /api/auth/google/helper/begin and
             then advances on its own when /api/auth/status flips to signed in;
             a failed begin shows in the card; the paste and separate-window
             flows sit under a collapsed "Other ways to sign in" details. No
             real browser: the begin route is stubbed.
"""

from __future__ import annotations

import pytest

from ._signin_helpers import reply, status_body, wait_text

pytestmark = pytest.mark.asyncio(loop_scope="session")

HELLO = "#fp-auth-google-hello"
HELLO_STATUS = "#fp-auth-google-hello-status"
HELLO_ERROR = "#fp-auth-google-hello-error"


async def _open(page, base_url, status: dict | None = None) -> None:
    """Open Settings > Sign-in WITHOUT revealing the details (poll fast)."""
    await page.add_init_script("window.__FP_TEST_STATUS_POLL_MS__ = 40;")
    await page.route("**/api/auth/status", reply(status or status_body()))
    await page.goto(base_url + "/#dashboard")
    await page.click("#btn-settings")
    await page.wait_for_selector("#fp-auth-google-status:not(:empty)", timeout=15000)


async def test_the_primary_button_is_sign_in_with_google_and_details_collapsed(page, base_url):
    await _open(page, base_url)
    assert await page.get_by_role("button", name="Sign in with Google").is_visible()
    details = page.locator("#fp-auth-google-card details.fp-signin-other")
    assert await details.get_attribute("open") is None  # collapsed by default
    # the demoted controls are inside it
    assert await details.locator("#fp-auth-google-open").count() == 1
    assert await details.locator("#fp-auth-google-signin").count() == 1


async def test_click_begins_and_auto_advances_on_status(page, base_url):
    began = []
    signed = {"in": False}

    async def begin_route(route):
        began.append(1)
        signed["in"] = True  # the helper posts the token; status now flips
        await route.fulfill(json={"browser": "chrome"})

    async def status_route(route):
        await route.fulfill(json=status_body(google=signed["in"]))

    await _open(page, base_url)
    await page.unroute("**/api/auth/status")
    await page.route("**/api/auth/status", status_route)
    await page.route("**/api/auth/google/helper/begin", begin_route)

    await page.get_by_role("button", name="Sign in with Google").click()
    await wait_text(page, "#fp-auth-google-status", "Signed in as g@example.com")
    assert began == [1]


async def test_unlock_step_appears_after_a_helper_sign_in(page, base_url):
    signed = {"in": False}

    async def begin_route(route):
        signed["in"] = True
        await route.fulfill(json={"browser": "chrome"})

    async def status_route(route):
        await route.fulfill(
            json=status_body(google=signed["in"], needs_g=["shared_key"] if signed["in"] else [])
        )

    await _open(page, base_url)
    await page.unroute("**/api/auth/status")
    await page.route("**/api/auth/status", status_route)
    await page.route("**/api/auth/google/helper/begin", begin_route)

    await page.get_by_role("button", name="Sign in with Google").click()
    await page.locator("#fp-auth-google-unlock").wait_for(state="visible", timeout=15000)


async def test_a_failed_begin_shows_in_the_card_with_retry(page, base_url):
    await _open(page, base_url)
    await page.route(
        "**/api/auth/google/helper/begin", reply({"detail": "Internal Server Error"}, 500)
    )
    await page.get_by_role("button", name="Sign in with Google").click()
    await wait_text(page, HELLO_ERROR, "Internal Server Error")
    assert await page.locator(HELLO_ERROR).get_by_role("button", name="Try again").is_visible()


async def test_other_ways_reveals_the_paste_and_separate_window_flows(page, base_url):
    await _open(page, base_url)
    await page.locator("#fp-auth-google-card details.fp-signin-other > summary").click()
    assert await page.get_by_role("button", name="Sign in with your Chrome").is_visible()
    assert await page.get_by_role(
        "button", name="Or let Find+ open its own Chrome window"
    ).is_visible()

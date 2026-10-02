"""The primary "Sign in with Google" button (the Chrome-helper flow).

Purpose    : the neutral primary button posts /api/auth/google/helper/begin and
             then advances on its own when /api/auth/status flips to signed in;
             a failed begin shows in the card; the paste flow sits under a
             collapsed "More ways to sign in"; the one-time helper install is
             written steps that open nothing. No real browser: routes stubbed.
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
    await wait_text(page, "#fp-auth-google-status", "Connected as g@example.com")
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


async def test_more_ways_keeps_the_paste_flow_and_hides_the_own_window(page, base_url):
    await _open(page, base_url)
    summary = page.locator("#fp-auth-google-card details.fp-signin-other > summary")
    assert await summary.inner_text() == "More ways to sign in"
    await summary.click()
    assert await page.get_by_role("button", name="Sign in with your Chrome").is_visible()
    # 1.2 hides Find+'s own Chrome window (spec Q4: hide in 1.2, remove in 1.3).
    assert await page.locator("#fp-auth-google-signin").is_hidden()


async def test_helper_install_is_written_steps_that_open_nothing(page, base_url):
    """1.2: no "Show helper folder" / "Open Chrome extensions" buttons (they
    opened Finder and a Chrome tab). The steps are text with two Copy buttons;
    the folder path comes from POST .../helper/folder, which opens nothing."""
    folder = []
    opened = []
    await _open(page, base_url)
    await page.route(
        "**/api/auth/google/helper/folder",
        reply({"path": "/x/.findplus/chrome-helper/1.2.0"}, 200, folder),
    )
    for route in ("reveal", "open-extensions"):
        await page.route(f"**/api/auth/google/helper/{route}", reply({}, 200, opened))
    card = page.locator("#fp-auth-google-card")
    assert await card.get_by_role("button", name="Show helper folder").count() == 0
    assert await card.get_by_role("button", name="Open Chrome extensions").count() == 0
    await page.locator("#fp-auth-google-card details.fp-signin-install > summary").click()
    await wait_text(page, "#fp-auth-google-helper-folder", "/x/.findplus/chrome-helper/1.2.0")
    assert await page.locator("#fp-auth-google-helper-extensions").inner_text() == (
        "chrome://extensions"
    )
    await page.click("#fp-auth-google-helper-folder-copy")
    assert len(folder) == 1 and opened == []


async def test_helper_folder_falls_back_to_the_plain_path(page, base_url):
    await _open(page, base_url)
    await page.route("**/api/auth/google/helper/folder", reply({"detail": "Not Found"}, 404))
    await page.locator("#fp-auth-google-card details.fp-signin-install > summary").click()
    await page.wait_for_timeout(300)
    assert "chrome-helper" in await page.locator("#fp-auth-google-helper-folder").inner_text()


async def test_helper_installed_line_follows_status(page, base_url):
    body = {"providers": status_body()["providers"], "google_helper_installed": True}
    await _open(page, base_url, body)
    await page.locator("#fp-auth-google-card details.fp-signin-install > summary").click()
    assert await page.locator("#fp-auth-google-helper-installed").is_visible()

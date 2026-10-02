"""Lost sign-in: one banner, one button, straight into the same login.

Purpose    : When /api/status says a provider needs the person (`attention`:
             reauth or unlock), the dashboard banner says so in plain words with
             ONE button ("Sign in again" / "Unlock locations") that opens
             Settings and starts the fix: the Find+ window in the desktop app,
             the Chrome helper in a browser tab, the Apple sheet for Apple. The
             shell's `auth-attention` event re-reads the banner at once, and its
             `signin-apple-sheet` event opens the Apple sheet. The Settings card
             shows the same state (attention box and the locked chip).
Constraints: /api/status is the real response with only provider_health
             replaced; the sign-in routes are the fake daemon. No real window.
"""

from __future__ import annotations

import pytest

from ._native_stub import ACCOUNT, FakeNativeDaemon, auth_status, emit, install_bridge, invokes
from ._signin_helpers import wait_text

pytestmark = pytest.mark.asyncio(loop_scope="session")

ACTION = "#alert .alert-action"


def _health(google="none", apple="none") -> list[dict]:
    return [
        {"name": "google-find-hub", "available": True, "authenticated": True, "attention": google},
        {"name": "apple-find-my", "available": True, "authenticated": True, "attention": apple},
    ]


async def _status_with(page, holder: dict) -> None:
    async def status_route(route):
        response = await route.fetch()
        body = await response.json()
        body["provider_health"] = holder["health"]
        body["last_poll"] = None
        await route.fulfill(json=body)

    await page.route("**/api/status", status_route)


async def _dashboard(page, base_url, holder, *, native=True) -> FakeNativeDaemon:
    if native:
        await install_bridge(page)
    fake = FakeNativeDaemon(page)
    await fake.install()
    await _status_with(page, holder)
    await page.goto(base_url + "/#dashboard")
    return fake


async def test_reauth_banner_one_tap_opens_the_window_and_ends_connected(page, base_url):
    holder = {"health": _health(google="reauth")}
    fake = await _dashboard(page, base_url, holder)
    fake.status = auth_status(att_g="reauth")
    await wait_text(page, "#alert", "Google signed Find+ out")
    assert await page.locator(ACTION).count() == 1
    assert await page.locator(ACTION).inner_text() == "Sign in again"
    await page.click(ACTION)
    await wait_text(page, "#fp-auth-google-native-text", "A Find+ sign-in window opened")
    assert (await invokes(page))[0]["mode"] == "signin"
    assert await page.locator("#fp-auth-google-revoked").is_visible()  # the Settings card agrees

    holder["health"] = _health()
    fake.status = auth_status(google=True)
    fake.set_phase("success", account=ACCOUNT, unlocked=True)
    await wait_text(page, "#fp-auth-google-status", f"Connected as {ACCOUNT}")
    assert await page.locator("#fp-auth-google-revoked").is_hidden()


async def test_unlock_banner_opens_the_window_in_unlock_mode(page, base_url):
    holder = {"health": _health(google="unlock")}
    fake = await _dashboard(page, base_url, holder)
    fake.status = auth_status(google=True, needs_g=["shared_key"], att_g="unlock")
    await wait_text(page, "#alert", "locations are locked again")
    assert await page.locator(ACTION).inner_text() == "Unlock locations"
    await page.click(ACTION)
    await wait_text(page, "#fp-auth-google-native-text", "Enter your Android phone's screen lock")
    assert (await invokes(page))[0]["mode"] == "unlock"
    assert fake.begins[0]["body"] == {"mode": "unlock"}
    assert await page.locator("#fp-auth-google-locked").is_visible()


async def test_the_shell_event_brings_the_banner_without_waiting(page, base_url):
    holder = {"health": _health()}
    await _dashboard(page, base_url, holder)
    await page.wait_for_function("() => window.__fpShell.listeners['auth-attention']")
    holder["health"] = _health(apple="reauth")
    await emit(page, "auth-attention", {"google": None, "apple": "signin"})
    await wait_text(page, "#alert", "Apple signed Find+ out")


async def test_the_apple_sheet_event_and_banner_open_the_sheet(page, base_url):
    holder = {"health": _health(apple="reauth")}
    fake = await _dashboard(page, base_url, holder)
    fake.status = auth_status(apple=True, att_a="reauth")
    await wait_text(page, "#alert", "Apple signed Find+ out")
    await page.click(ACTION)
    sheet = page.locator("#fp-auth-apple-sheet")
    await page.wait_for_function("() => document.getElementById('fp-auth-apple-sheet').open")
    await page.keyboard.press("Escape")
    assert not await sheet.evaluate("(d) => d.open")
    await emit(page, "signin-apple-sheet", None)
    await page.wait_for_function("() => document.getElementById('fp-auth-apple-sheet').open")


async def test_in_a_browser_tab_the_banner_starts_the_chrome_helper(page, base_url):
    holder = {"health": _health(google="reauth")}
    began: list[str] = []

    async def helper_begin(route):
        began.append(route.request.url)
        await route.fulfill(json={"generation": 1})

    fake = await _dashboard(page, base_url, holder, native=False)
    fake.status = auth_status(att_g="reauth")
    await page.route("**/api/auth/google/helper/begin", helper_begin)
    await wait_text(page, "#alert", "Google signed Find+ out")
    await page.click(ACTION)
    await page.locator("#fp-auth-google-hello-status").wait_for(state="visible", timeout=15000)
    assert len(began) == 1
    assert await page.locator("#fp-auth-google-native").count() == 0

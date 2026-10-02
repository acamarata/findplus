"""The Find+ window against the REAL daemon: blocked, closed, failed, locked.

Purpose    : Drive the real in-app sign-in routes (contract §3) end to end with
             the stub bridge: the card's own begin (same-origin, with its
             session cookie) is handed to the shell; the "shell" here posts the
             window's events back exactly as Rust does (Origin + X-FindPlus-
             Client). A block shows the daemon's words and the fallback
             ladder's next step, and the card then leads with your Chrome for
             a few days with a quiet "Try the Find+ window again". Closing the
             window is "Cancelled"; a failed window is an error with Retry.
             Behind the app lock only the card can begin, never a cookieless
             caller, which is why the card hands its begin to the shell.
Constraints: No token is ever posted (that would reach Google). The 7-day block
             memory file is removed afterwards, and the PIN is removed in a
             finally, so the shared server is left as it was found.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import httpx
import pytest

from ._native_stub import install_bridge, invokes, shell_event
from ._signin_helpers import wait_text
from .test_lock import PIN

pytestmark = pytest.mark.asyncio(loop_scope="session")

TEXT = "#fp-auth-google-native-text"


async def _open(page, base_url) -> None:
    await install_bridge(page)
    await page.route("**/api/auth/google/helper/begin", lambda r: r.fulfill(json={"ok": True}))
    await page.goto(base_url + "/#dashboard")
    await page.click("#btn-settings")
    await page.wait_for_selector("#fp-auth-google-status:not(:empty)", timeout=15000)


async def _connect(page) -> str:
    await page.click("#fp-auth-google-native-connect")
    await wait_text(page, TEXT, "A Find+ sign-in window opened")
    begin = (await invokes(page))[0]["begin"]
    assert begin["mode"] == "signin" and begin["window"]["label"] == "signin-google"
    return begin["state"]


@pytest.fixture
def forget_block(ui_env):
    yield
    Path(ui_env["FINDPLUS_STATE_DIR"], "native-signin.json").unlink(missing_ok=True)


async def test_blocked_shows_the_ladder_then_starts_with_chrome(page, base_url, forget_block):
    await _open(page, base_url)
    state = await _connect(page)
    await shell_event(base_url, state, "opened")
    answer = await shell_event(base_url, state, "blocked", "rejected_page")
    assert answer["phase"] == "blocked_embedded"
    await wait_text(page, TEXT, "Google would not let Find+ sign you in inside the app")
    assert await page.locator("#fp-auth-google-card").get_attribute("data-phase") == (
        "blocked_embedded"
    )
    assert await page.locator("#fp-auth-google-native-window-again").is_visible()
    if answer["fallback"] == "use_paste":  # no Chrome on this machine
        await page.click("#fp-auth-google-native-paste")
        assert await page.evaluate("() => document.activeElement.id") == "fp-auth-google-open"
    else:
        await page.click("#fp-auth-google-native-chrome")
        await page.locator("#fp-auth-google-hello-status").wait_for(state="visible")
    assert await page.locator("#fp-auth-google-more").get_attribute("open") is not None

    # For the next 7 days the card leads with your Chrome.
    await page.reload()
    await page.click("#btn-settings")
    await page.locator("#fp-auth-google-native-window-again").wait_for(state="visible")
    assert await page.locator("#fp-auth-google-native-connect").is_hidden()
    note = await page.locator("#fp-auth-google-native-note").inner_text()
    assert "starts with your Chrome" in note


async def test_closing_the_window_is_cancelled(page, base_url):
    await _open(page, base_url)
    state = await _connect(page)
    await shell_event(base_url, state, "closed")
    await wait_text(page, TEXT, "Cancelled. Nothing changed.")
    assert await page.locator("#fp-auth-google-native-connect").is_visible()


async def test_a_failed_window_is_an_error_with_retry(page, base_url):
    await _open(page, base_url)
    state = await _connect(page)
    await shell_event(base_url, state, "failed", "load_failed")
    await wait_text(page, TEXT, "The sign-in page did not load")
    assert await page.locator("#fp-auth-google-native-retry").is_visible()
    # Cancel leaves no state behind for the next test.
    await page.evaluate("() => fetch('/api/auth/google/native/cancel', {method: 'POST'})")


async def test_behind_the_lock_only_the_card_can_begin(page, base_url):
    """The shell has no session cookie: its own begin is a 401 while locked,
    so the card's begin (made after the PIN) is what opens the window."""

    async def post(path, body):
        return await page.request.post(
            base_url + path, data=json.dumps(body), headers={"Content-Type": "application/json"}
        )

    assert (await post("/api/settings/pin", {"new_pin": PIN})).ok
    try:
        assert (await page.request.post(base_url + "/api/lock/lock")).ok
        async with httpx.AsyncClient() as client:  # what Rust would send: no cookie
            bare = await client.post(
                base_url + "/api/auth/google/native/begin",
                json={"mode": "signin"},
                headers={"Origin": base_url},
            )
        assert bare.status_code == 401
        await _open_locked(page, base_url)
        state = await _connect(page)
        assert len(state) >= 40
        await page.evaluate("() => fetch('/api/auth/google/native/cancel', {method: 'POST'})")
    finally:
        with contextlib.suppress(Exception):
            await post("/api/lock/unlock", {"pin": PIN})
        await page.request.delete(
            base_url + "/api/settings/pin",
            data=json.dumps({"current_pin": PIN}),
            headers={"Content-Type": "application/json"},
        )


async def _open_locked(page, base_url) -> None:
    await install_bridge(page)
    await page.goto(base_url + "/#dashboard")
    await page.locator("#lock-screen").wait_for(state="visible", timeout=15000)
    await page.fill("#lock-pin", PIN)
    await page.click("#lock-submit")
    await page.locator("#lock-screen").wait_for(state="hidden", timeout=15000)
    await page.click("#btn-settings")
    await page.wait_for_selector("#fp-auth-google-status:not(:empty)", timeout=15000)

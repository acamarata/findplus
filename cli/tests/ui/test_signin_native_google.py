"""Google in the Find+ window: Connect, the window's states, and how it ends.

Purpose    : In the desktop app (stub bridge, _native_stub.py) the Google card's
             one Connect button posts begin, hands the WHOLE reply to the shell
             (`open_signin_window`), follows the shell's events and polls
             progress, and finishes with "Connected as ..." plus "Locations
             unlocked", focus on that line. Also: the unlock step in the same
             window, Cancel, a timeout, a window that could not open, polling
             alone when the bridge has no event API, Show window, and a locked
             daemon answering begin with 401.
Constraints: Fake daemon (page.route) for the parts a real token exchange
             would need; no real window, Chrome or network.
"""

from __future__ import annotations

import pytest

from ._native_stub import (
    ACCOUNT,
    FakeNativeDaemon,
    auth_status,
    emit,
    install_bridge,
    invokes,
    live_log,
)
from ._signin_helpers import wait_text

pytestmark = pytest.mark.asyncio(loop_scope="session")

CARD = "#fp-auth-google-card"
TEXT = "#fp-auth-google-native-text"
CONNECT = "#fp-auth-google-native-connect"


async def _open(page, base_url, **bridge) -> FakeNativeDaemon:
    await install_bridge(page, **bridge)
    fake = FakeNativeDaemon(page)
    await fake.install()
    await page.goto(base_url + "/#dashboard")
    await page.click("#btn-settings")
    await page.wait_for_selector("#fp-auth-google-status:not(:empty)", timeout=15000)
    return fake


async def _connect(page, fake) -> None:
    await live_log(page, "#fp-auth-google-native-status")
    await page.click(CONNECT)
    await wait_text(page, TEXT, "A Find+ sign-in window opened")
    fake.set_phase("waiting")


async def _phase(page) -> str:
    return await page.locator(CARD).get_attribute("data-phase")


async def test_connect_hands_begin_to_the_window_and_ends_connected(page, base_url):
    fake = await _open(page, base_url)
    assert await page.locator(CONNECT).inner_text() == "Connect"
    await _connect(page, fake)
    calls = await invokes(page)
    assert calls == [
        {
            "provider": "google",
            "mode": "signin",
            "begin": {
                "state": "fake-state",
                "mode": "signin",
                "window": {"timeout_seconds": 600},
                "generation": 1,
                "flow": "flow1",
            },
        }
    ]
    assert fake.begins[0]["body"] == {"mode": "signin", "if_idle": True}
    assert fake.begins[0]["origin"] == base_url
    assert await page.locator("#fp-auth-google-native-show").is_visible()
    note = await page.locator("#fp-auth-google-native-note").inner_text()
    assert "title" in note  # the window-title note

    await emit(
        page,
        "signin-progress",
        {"provider": "google", "mode": "signin", "phase": "finishing", "stuck": False},
    )
    await wait_text(page, TEXT, "Checking with Google")
    fake.set_phase("success", account=ACCOUNT, unlocked=True)
    fake.status = auth_status(google=True)
    await emit(
        page,
        "signin-result",
        {
            "provider": "google",
            "mode": "signin",
            "outcome": "success",
            "unlocked": True,
            "account": ACCOUNT,
        },
    )
    await wait_text(page, "#fp-auth-google-status", f"Connected as {ACCOUNT}")
    assert await page.locator("#fp-auth-google-ready").inner_text() == "Locations unlocked"
    await page.wait_for_function(
        "() => document.activeElement && document.activeElement.id === 'fp-auth-google-status'"
    )
    assert await _phase(page) == "success"
    said = await page.evaluate("() => window.__fpLive")
    assert len(said) == len(set(said)), said  # each state announced once


async def test_needs_unlock_runs_in_the_same_window_then_success(page, base_url):
    fake = await _open(page, base_url)
    await _connect(page, fake)
    fake.set_phase("needs_unlock", account=ACCOUNT)
    await wait_text(page, TEXT, "One more step: enter your Android phone's screen lock")
    assert await _phase(page) == "needs_unlock"
    assert len(await invokes(page)) == 1  # no second window
    fake.status = auth_status(google=True)
    fake.set_phase("success", account=ACCOUNT, unlocked=True)
    await wait_text(page, "#fp-auth-google-status", f"Connected as {ACCOUNT}")
    assert await page.locator("#fp-auth-google-ready").is_visible()


async def test_cancel_drops_the_state_and_closes_the_window(page, base_url):
    fake = await _open(page, base_url)
    await _connect(page, fake)
    await page.click("#fp-auth-google-native-cancel")
    await wait_text(page, TEXT, "Cancelled. Nothing changed.")
    await page.wait_for_function(
        "() => window.__fpShell.calls.some((c) => c.cmd === 'close_signin_window')"
    )
    assert fake.cancels == 1
    assert await invokes(page, "close_signin_window") == [{"provider": "google"}]
    assert await page.locator(CONNECT).is_visible()
    assert await _phase(page) == "idle"


async def test_a_timeout_says_so_and_retry_begins_again(page, base_url):
    fake = await _open(page, base_url)
    await _connect(page, fake)
    await emit(
        page,
        "signin-result",
        {
            "provider": "google",
            "mode": "signin",
            "outcome": "timeout",
            "unlocked": False,
            "account": None,
        },
    )
    await wait_text(page, TEXT, "open too long")
    assert await _phase(page) == "error"
    await page.click("#fp-auth-google-native-retry")
    await wait_text(page, TEXT, "A Find+ sign-in window opened")
    assert len(fake.begins) == 2


async def test_progress_alone_drives_the_card_without_an_event_api(page, base_url):
    fake = await _open(page, base_url, noEvents=True)
    await _connect(page, fake)
    fake.set_phase("finishing")
    await wait_text(page, TEXT, "Checking with Google")
    fake.status = auth_status(google=True, needs_g=["shared_key"])
    fake.set_phase("success", account=ACCOUNT, unlocked=False)
    await wait_text(page, "#fp-auth-google-status", f"Connected as {ACCOUNT}")
    # Not unlocked: the locked chip and the unlock step, which uses the window.
    assert await page.locator("#fp-auth-google-locked").is_visible()
    await page.click("#fp-auth-google-unlock-btn")
    await wait_text(page, TEXT, "A Find+ window opened. Enter your Android phone's screen lock")
    assert (await invokes(page))[-1]["mode"] == "unlock"
    assert fake.begins[-1]["body"] == {"mode": "unlock", "if_idle": True}


async def test_a_window_that_cannot_open_is_an_error_with_a_way_out(page, base_url):
    fake = await _open(page, base_url, fail=True)
    await page.click(CONNECT)
    await wait_text(page, TEXT, "could not open its sign-in window")
    await page.wait_for_timeout(300)  # the best-effort cancel lands after the message
    assert fake.cancels == 1
    assert await page.locator("#fp-auth-google-native-retry").is_visible()
    assert await page.locator("#fp-auth-google-native-chrome").is_visible()


async def test_show_window_focuses_it_without_a_new_begin(page, base_url):
    fake = await _open(page, base_url)
    await _connect(page, fake)
    await page.click("#fp-auth-google-native-show")
    await page.wait_for_function("() => window.__fpShell.calls.length >= 2")
    calls = await invokes(page)
    assert calls[-1] == {"provider": "google", "mode": "signin"}
    assert len(fake.begins) == 1


async def test_a_locked_daemon_stops_quietly(page, base_url):
    fake = await _open(page, base_url)
    fake.begin_status = 401
    await page.click(CONNECT)
    await page.locator("#lock-screen").wait_for(state="visible", timeout=15000)
    assert await invokes(page) == []


async def test_a_window_the_tray_opened_is_followed_too(page, base_url):
    fake = await _open(page, base_url)
    fake.set_phase("waiting", mode="signin")
    await emit(
        page,
        "signin-progress",
        {"provider": "google", "mode": "signin", "phase": "waiting", "stuck": False},
    )
    await wait_text(page, TEXT, "Finish signing in in the Find+ window")
    await emit(
        page,
        "signin-progress",
        {"provider": "google", "mode": "signin", "phase": "waiting", "stuck": True},
    )
    await wait_text(page, "#fp-auth-google-native-note", "Taking a while")
    assert await invokes(page) == []

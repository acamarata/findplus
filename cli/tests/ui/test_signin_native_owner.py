"""The Google card follows the daemon's truth: one window, one flow (contract §3.8).

Purpose    : r12 #1, #3 and #4 from the card's side. Try again while the window
             is still working follows that window (no new begin is handed to
             the shell, so its state survives); a success from the card's own
             flow lands even after an error was shown; news from an older
             window's flow never moves a newer sign-in; an unlock-only window
             that could not read the account shows the plain reason and Try
             again.
Constraints: Stub bridge and fake daemon (_native_stub.py); no real window,
             Chrome or network. Neutral names only.
"""

from __future__ import annotations

import pytest

from ._native_stub import ACCOUNT, FakeNativeDaemon, auth_status, emit, install_bridge, invokes
from ._signin_helpers import wait_text

pytestmark = pytest.mark.asyncio(loop_scope="session")

CARD = "#fp-auth-google-card"
TEXT = "#fp-auth-google-native-text"
CONNECT = "#fp-auth-google-native-connect"
RETRY = "#fp-auth-google-native-retry"
UNKNOWN = (
    "Find+ could not tell which Google account the window is signed in to, so it saved "
    "nothing. Try again."
)


async def _open(page, base_url) -> FakeNativeDaemon:
    await install_bridge(page)
    fake = FakeNativeDaemon(page)
    await fake.install()
    await page.goto(base_url + "/#dashboard")
    await page.click("#btn-settings")
    await page.wait_for_selector("#fp-auth-google-status:not(:empty)", timeout=15000)
    return fake


async def _phase(page) -> str:
    return await page.locator(CARD).get_attribute("data-phase")


async def _result(page, outcome: str, flow: str | None, **extra) -> None:
    payload = {"provider": "google", "mode": "signin", "outcome": outcome, "flow": flow}
    await emit(page, "signin-result", {**payload, **extra})


async def test_try_again_follows_a_window_that_is_still_working(page, base_url):
    fake = await _open(page, base_url)
    await page.click(CONNECT)
    await wait_text(page, TEXT, "A Find+ sign-in window opened")
    fake.set_phase("error", message="Something went wrong.")
    await page.wait_for_function(
        f"() => document.querySelector('{CARD}').dataset.phase === 'error'"
    )
    # The daemon says the window still works: begin answers 409 window_open.
    fake.begin_status = 409
    fake.open_window = {"flow": "flow1", "mode": "signin"}
    fake.set_phase("waiting", flow="flow1")
    await page.click(RETRY)
    await page.wait_for_function(
        f"() => document.querySelector('{CARD}').dataset.phase === 'waiting'"
    )
    calls = await invokes(page)
    assert "begin" in calls[0] and "begin" not in calls[-1]  # focused, never replaced
    assert len(fake.begins) == 2
    fake.set_phase("success", account=ACCOUNT, unlocked=True, flow="flow1")
    fake.status = auth_status(google=True)
    await wait_text(page, "#fp-auth-google-status", f"Connected as {ACCOUNT}")


async def test_its_own_late_success_lands_after_an_error(page, base_url):
    fake = await _open(page, base_url)
    await page.click(CONNECT)
    await wait_text(page, TEXT, "A Find+ sign-in window opened")
    await _result(page, "error", "flow1", message="Couldn't reach Google.")
    await page.wait_for_function(
        f"() => document.querySelector('{CARD}').dataset.phase === 'error'"
    )
    fake.status = auth_status(google=True)
    await _result(page, "success", "flow1", unlocked=True, account=ACCOUNT)
    await wait_text(page, "#fp-auth-google-status", f"Connected as {ACCOUNT}")
    assert await _phase(page) == "success"


async def test_an_older_window_never_finishes_a_newer_sign_in(page, base_url):
    fake = await _open(page, base_url)
    fake.flow = "flow2"
    await page.click(CONNECT)
    await wait_text(page, TEXT, "A Find+ sign-in window opened")
    fake.set_phase("waiting", flow="flow2")
    await _result(page, "success", "flow1", unlocked=True, account=ACCOUNT)
    fake.set_phase("success", account=ACCOUNT, flow="flow1")  # a stale answer
    await page.wait_for_timeout(400)
    assert await _phase(page) == "waiting"
    await emit(
        page,
        "signin-progress",
        {"provider": "google", "mode": "signin", "phase": "finishing", "flow": "flow1"},
    )
    await page.wait_for_timeout(200)
    assert await _phase(page) == "waiting"


async def test_unlock_without_a_known_account_says_why_and_offers_retry(page, base_url):
    fake = await _open(page, base_url)
    await page.click(CONNECT)
    await wait_text(page, TEXT, "A Find+ sign-in window opened")
    fake.set_phase("error", message=UNKNOWN, reason="account_unknown", flow="flow1")
    await wait_text(page, TEXT, "could not tell which Google account")
    assert await page.locator(RETRY).is_visible()
    assert await page.locator(TEXT).inner_text() == UNKNOWN


async def test_the_card_says_what_find_keeps_before_the_window_opens(page, base_url):
    """r12 #5: consent first. Both sentences come from honesty.py, verbatim."""
    from findplus import honesty

    await _open(page, base_url)
    assert await page.locator(CONNECT).is_visible()
    kept = page.locator("#fp-auth-google-native-kept")
    assert await kept.is_visible()
    assert await kept.inner_text() == honesty.NATIVE_SIGNIN_KEPT
    refuse = page.locator("#fp-auth-google-native-honesty")
    assert await refuse.inner_text() == honesty.NATIVE_SIGNIN
    assert await page.evaluate("() => window.__fpShell.calls.length") == 0  # nothing opened yet

"""Every Google sign-in state, driven through stubbed auth routes (E14).

Purpose    : The owner clicked "Sign in with Google", nothing opened, and the
             page said nothing. The shared sign-in component (web/app/signin/)
             now shows each state GET /api/auth/google/progress can report, and
             every way a sign-in can fail, in plain words with a Retry button.
             This file walks those states on the wizard's sign-in step;
             test_signin_states_apple.py covers Apple and Settings.
Constraints: No real Chrome and no provider: POST /api/auth/google/start and
             the progress route are answered by page.route. Expected text is
             read from the served catalog, never retyped.
"""

from __future__ import annotations

import pytest

from findplus import honesty

from ._signin_helpers import (
    abort,
    open_wizard_signin,
    reply,
    restore_onboarding,
    status_body,
    wait_text,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

CONNECT = "Connect Google Find Hub"
ERROR = "#fp-setup-google-error"
PROGRESS = "#fp-setup-google-progress"


async def _catalog(page, base_url) -> dict:
    response = await page.request.get(base_url + "/static/locales/en.json")
    return (await response.json())["signin"]


async def _start_job(page, progress: dict) -> None:
    """Start answers a job id; every poll of it answers `progress`."""
    await page.route("**/api/auth/google/start", reply({"job_id": "job-1"}, 202))
    await page.route("**/api/auth/google/progress*", reply({"chrome_found": True, **progress}))


@pytest.mark.parametrize(
    ("state", "key"),
    [("launching", "starting"), ("waiting_for_user", "waiting"), ("capturing", "capturing")],
)
async def test_each_running_state_says_what_is_happening(page, base_url, state, key):
    try:
        await open_wizard_signin(page, base_url)
        catalog = await _catalog(page, base_url)
        await _start_job(page, {"state": state, "message": ""})
        await page.get_by_role("button", name=CONNECT).click()
        await wait_text(page, PROGRESS, catalog["google"][key])
        assert await page.get_by_role("button", name=CONNECT).is_disabled()
        assert await page.locator(ERROR).is_hidden()
    finally:
        await restore_onboarding(page, base_url)


async def test_the_click_shows_opening_chrome_before_the_first_poll(page, base_url):
    """Feedback on the click itself, not two seconds later."""
    held = []

    async def hold(route):
        held.append(route)  # never answered: the start request stays in flight

    try:
        await open_wizard_signin(page, base_url)
        await page.route("**/api/auth/google/start", hold)
        await page.get_by_role("button", name=CONNECT).click()
        await wait_text(page, PROGRESS, "Opening Chrome")
    finally:
        for route in held:
            await route.abort()
        await restore_onboarding(page, base_url)


async def test_a_refused_start_is_shown_with_retry(page, base_url):
    """The owner's bug: a daemon error on start used to be a silent no-op."""
    calls: list[str] = []
    try:
        await open_wizard_signin(page, base_url)
        await page.route(
            "**/api/auth/google/start", reply({"detail": "Internal Server Error"}, 500, calls)
        )
        await page.get_by_role("button", name=CONNECT).click()
        await wait_text(page, ERROR, "could not start the sign-in: Internal Server Error")
        assert await page.locator(PROGRESS).is_hidden()
        assert await page.get_by_role("button", name=CONNECT).is_enabled()

        await page.locator(ERROR).get_by_role("button", name="Try again").click()
        await wait_text(page, ERROR, "Internal Server Error")
        assert len(calls) == 2, calls
    finally:
        await restore_onboarding(page, base_url)


async def test_an_unreachable_daemon_on_start_is_shown(page, base_url):
    try:
        await open_wizard_signin(page, base_url)
        catalog = await _catalog(page, base_url)
        await page.route("**/api/auth/google/start", abort)
        await page.get_by_role("button", name=CONNECT).click()
        await wait_text(page, ERROR, catalog["error"]["unreachable"])
    finally:
        await restore_onboarding(page, base_url)


async def test_a_failed_job_shows_the_servers_reason(page, base_url):
    """The daemon's own timeout (5-minute cookie wait) arrives as `failed`."""
    timeout_message = "No sign-in was completed within 5 minutes. Try again."
    try:
        await open_wizard_signin(page, base_url)
        await _start_job(page, {"state": "failed", "message": timeout_message})
        await page.get_by_role("button", name=CONNECT).click()
        await wait_text(page, ERROR, timeout_message)
        assert await page.locator("#fp-setup-google-card").get_attribute("data-state") == "failed"
        retry = page.locator(ERROR).get_by_role("button", name="Try again")
        assert await retry.is_visible()
    finally:
        await restore_onboarding(page, base_url)


async def test_a_forgotten_job_says_it_expired(page, base_url):
    try:
        await open_wizard_signin(page, base_url)
        catalog = await _catalog(page, base_url)
        await page.route("**/api/auth/google/start", reply({"job_id": "gone"}, 202))
        await page.route(
            "**/api/auth/google/progress*", reply({"detail": "unknown or expired job_id"}, 404)
        )
        await page.get_by_role("button", name=CONNECT).click()
        await wait_text(page, ERROR, catalog["error"]["expired"])
    finally:
        await restore_onboarding(page, base_url)


async def test_losing_the_daemon_mid_job_is_shown(page, base_url):
    """Three failed polls in a row (one is only noise) end the wait with a reason."""
    try:
        await open_wizard_signin(page, base_url)
        catalog = await _catalog(page, base_url)
        await page.route("**/api/auth/google/start", reply({"job_id": "job-2"}, 202))
        await page.route("**/api/auth/google/progress*", abort)
        await page.get_by_role("button", name=CONNECT).click()
        await wait_text(page, ERROR, catalog["error"]["unreachable"], timeout=20000)
    finally:
        await restore_onboarding(page, base_url)


async def test_a_job_that_never_ends_times_out_on_the_client(page, base_url):
    """The client cap (job_poller.js POLL_CAP) ends a poll the daemon never
    settles. page.clock can fast-forward virtual time, but each poll still
    goes out as a real fetch that a mocked route has to answer for real, so
    fast-forwarding through the full 200-poll/2s cadence meant 202 real
    round trips -- fast on a quiet machine, but slow enough under CI load to
    blow past wait_text's 15 s budget before the last one lands. job_poller.js
    now reads its cadence and cap from window.__FP_TEST_POLL_MS__/
    __FP_TEST_POLL_CAP__ when set, so this drives the same tick-past-the-cap
    code path with 3 real (near-instant) polls instead of 202."""
    try:
        await page.add_init_script(
            "window.__FP_TEST_POLL_MS__ = 20; window.__FP_TEST_POLL_CAP__ = 3;"
        )
        await open_wizard_signin(page, base_url)
        catalog = await _catalog(page, base_url)
        await _start_job(page, {"state": "waiting_for_user", "message": ""})
        await page.get_by_role("button", name=CONNECT).click()
        await wait_text(page, ERROR, catalog["error"]["timeout"])
    finally:
        await restore_onboarding(page, base_url)


#: UAT6 N23: the notice drops honesty.CHROME_REQUIRED's own "Install it from
#: <url> and try again" clause -- the Download Chrome link right beside it is
#: that action, so the raw URL is not shown as plain text too.
_CHROME_NOTICE_TEXT = honesty.CHROME_REQUIRED.split(" Install it from")[0]


async def test_chrome_going_missing_mid_job_shows_the_notice(page, base_url):
    try:
        await open_wizard_signin(page, base_url)
        await page.route("**/api/auth/google/start", reply({"job_id": "job-3"}, 202))
        await page.route(
            "**/api/auth/google/progress*",
            reply({"state": "failed", "message": "x", "chrome_found": False}),
        )
        await page.get_by_role("button", name=CONNECT).click()
        await wait_text(page, "#fp-setup-chrome-notice", _CHROME_NOTICE_TEXT)
        assert "https://" not in await page.locator("#fp-setup-chrome-notice").inner_text()
        assert await page.locator("#fp-setup-chrome-download").is_visible()
        assert await page.get_by_role("button", name=CONNECT).is_disabled()
    finally:
        await restore_onboarding(page, base_url)


async def test_done_shows_the_account_and_offers_a_switch(page, base_url):
    """Success re-reads the status: the card and the step summary both say who."""
    try:
        await open_wizard_signin(page, base_url)
        await _start_job(page, {"state": "done", "message": "Authenticated as g@example.com."})
        await page.unroute("**/api/auth/status")
        await page.route("**/api/auth/status", reply(status_body(google=True)))
        await page.get_by_role("button", name=CONNECT).click()
        await wait_text(page, "#fp-setup-google-status", "Signed in as g@example.com")
        await wait_text(page, "#fp-setup-signin-status", "g@example.com")
        assert await page.locator(PROGRESS).is_hidden()
        assert await page.get_by_role("button", name="Switch Google account").is_enabled()
    finally:
        await restore_onboarding(page, base_url)

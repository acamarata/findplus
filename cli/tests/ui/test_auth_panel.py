"""Browser tests for the sign-in panel (P2-E10-W4-S1-T1, rulings R-P2-8/R-P2-11).

The panel is the first section of the Settings dialog, not a tab. No test here
clicks "Sign in with Google" or "Sign in with Apple" for real: a real Chrome
launch is out of scope for a headless run, and the autouse socket guard in
cli/tests/conftest.py blocks non-loopback traffic anyway. auth.js exports its
render functions precisely so every progress and 2FA state can be driven
deterministically from page.evaluate().

Every expected string is read from the live catalog (/static/locales/en.json),
never retyped, the same import-the-source-of-truth rule test_honesty_text.py
follows for honesty sentences.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

# E11's first-run check redirects a hash-less "/" to #/setup and hides
# #app-shell whenever onboarding.completed_at is null, which it always is in
# this suite's seeded state dir. A non-empty, inert hash (applyHashRoute only
# acts on #settings/#devices/#/setup) keeps the dashboard on screen; it stays
# correct once that precondition is seeded for the whole suite.
DASHBOARD = "/#dashboard"


async def _catalog(page, base_url) -> dict:
    """The served English catalog, as the dashboard itself loads it."""
    response = await page.request.get(base_url + "/static/locales/en.json")
    assert response.ok, await response.text()
    return await response.json()


async def _open_settings(page, base_url) -> None:
    """Go to the dashboard and open Settings.

    openSettings() (web/app/settings.js) unhides #settings-modal before any
    await now, so the click below no longer races state.config or needs a
    retry-and-diagnose loop (CI run 35546305331 fix) -- one deterministic
    wait for the sign-in panel's static host is enough to know the dialog
    is open.
    """
    await page.goto(base_url + DASHBOARD)
    await page.click("#btn-settings")
    await page.wait_for_selector("#fp-settings-signin")


async def _render_google_progress(page, progress: dict) -> None:
    """Call auth.js's exported renderer directly, with no job behind it."""
    await page.evaluate(
        """async (progress) => {
            const auth = await import('/static/app/auth.js');
            auth.renderGoogleProgress(progress);
        }""",
        progress,
    )


async def test_auth_status_cards_render_not_signed_in(page, base_url) -> None:
    await _open_settings(page, base_url)
    expected = (await _catalog(page, base_url))["auth"]["status"]["not_signed_in"]

    await page.wait_for_function(
        "(text) => document.getElementById('fp-auth-google-status').textContent === text",
        arg=expected,
    )
    assert await page.locator("#fp-auth-google-status").inner_text() == expected
    assert await page.locator("#fp-auth-apple-status").inner_text() == expected


async def test_each_provider_card_says_which_provider_it_is(page, base_url) -> None:
    """W3 visual gate finding 3: two identical status lines and no headings."""
    await _open_settings(page, base_url)
    catalog = (await _catalog(page, base_url))["auth"]

    google = page.locator("#fp-auth-google-card .fp-auth-provider")
    apple = page.locator("#fp-auth-apple-card .fp-auth-provider")
    assert await google.inner_text() == catalog["google"]["heading"]
    assert await apple.inner_text() == catalog["apple"]["heading"]


async def test_apple_2fa_field_hidden_by_default(page, base_url) -> None:
    await _open_settings(page, base_url)
    assert "hidden" in (await page.locator("#fp-auth-apple-2fa").get_attribute("class"))


async def test_google_progress_states_render(page, base_url) -> None:
    await _open_settings(page, base_url)
    google = (await _catalog(page, base_url))["auth"]["google"]

    for state, key in (
        ("launching", "launching"),
        ("waiting_for_user", "waiting"),
        ("capturing", "capturing"),
    ):
        await _render_google_progress(page, {"state": state, "message": "", "chrome_found": True})
        assert await page.locator("#fp-auth-google-progress").inner_text() == google[key]


async def test_google_chrome_missing_disables_button(page, base_url) -> None:
    await _open_settings(page, base_url)
    google = (await _catalog(page, base_url))["auth"]["google"]

    await _render_google_progress(page, {"state": "failed", "message": "x", "chrome_found": False})

    assert await page.locator("#fp-auth-google-signin").is_disabled()
    assert google["chrome_missing"] in await page.locator("#fp-auth-google-progress").inner_text()
    download = page.locator("#fp-auth-chrome-download")
    assert "hidden" not in (await download.get_attribute("class"))
    assert await download.get_attribute("href") == "https://www.google.com/chrome/"


async def test_the_chrome_honesty_sentence_comes_from_the_server(page, base_url) -> None:
    """Never typed into the markup: notices.js fills it from /api/config."""
    from findplus import honesty

    await _open_settings(page, base_url)
    await page.wait_for_function(
        "() => document.getElementById('fp-auth-chrome-notice').textContent.length > 0"
    )
    assert await page.locator("#fp-auth-chrome-notice").inner_text() == honesty.CHROME_REQUIRED


async def test_apple_2fa_field_shown_via_show_apple_2fa(page, base_url) -> None:
    await _open_settings(page, base_url)
    await page.evaluate(
        """async () => {
            const auth = await import('/static/app/auth.js');
            auth.showApple2fa(true);
        }"""
    )
    assert "hidden" not in (await page.locator("#fp-auth-apple-2fa").get_attribute("class"))


async def test_apple_password_field_type_is_password(page, base_url) -> None:
    await _open_settings(page, base_url)
    assert await page.locator("#fp-auth-apple-password").get_attribute("type") == "password"


async def test_the_lock_purge_empties_the_sign_in_panel(page, base_url) -> None:
    """CR-C-E10 F3: a closed <dialog> keeps its content behind the lock screen.

    The signed-in account, a typed Apple ID and an unsent password all stayed
    readable after a lock, because lock.js's purgeTabModules() had no auth.js
    entry. Driven through purgeRenderedData(), so the registration itself is
    what this asserts, not auth.purge() called directly.

    Order-flaky under full-suite load (loop3 L3-1, CI 35557336869): openSettings()
    (web/app/settings.js) mounts this panel via an unawaited loadAuthStatus()
    (auth.js mountAuthPanel), so _open_settings() above can return before that
    real GET /api/auth/status has even been issued, let alone resolved. If the
    manual override + purge below land first, the still-pending initial load
    finishes afterward with a fresh (post-purge) generation snapshot -- the
    guard in auth.js's loadAuthStatus() only discards a response that was
    already in flight *before* purge() bumped generation, so this one sails
    through and repopulates "Not signed in". Waiting here for that first load
    to actually render closes the gap deterministically, the same way
    test_google_says_not_signed_in above already does.
    """
    await _open_settings(page, base_url)
    await page.wait_for_function(
        "() => document.getElementById('fp-auth-google-status').textContent !== ''"
    )
    await page.fill("#fp-auth-apple-id", "someone@example.com")
    await page.fill("#fp-auth-apple-password", "not-a-real-password")
    await page.evaluate(
        """async () => {
            document.getElementById('fp-auth-google-status').textContent =
                'Signed in as someone@example.com';
            const lock = await import('/static/app/lock.js');
            await lock.purgeRenderedData();
        }"""
    )

    for field in ("fp-auth-apple-id", "fp-auth-apple-password", "fp-auth-apple-code"):
        assert await page.locator(f"#{field}").input_value() == "", field
    assert await page.locator("#fp-auth-google-status").inner_text() == ""
    assert await page.locator("#fp-auth-apple-status").inner_text() == ""


async def test_in_flight_status_response_does_not_repopulate_after_purge(page, base_url) -> None:
    """R-P2-8 / CI 35557336869: the test above raced a real GET /api/auth/status
    against purgeRenderedData() and was order-flaky (L3-1) because the request
    sometimes landed after the purge and refilled "Not signed in". This test
    holds the response open with page.route so the race is deterministic
    instead of depending on scheduler timing: it waits for openSettings()'s
    own GET /api/auth/status to actually reach the server (`request_started`)
    before purging, so the purge is guaranteed to land while that request is
    genuinely in flight, then releases it and checks it was a no-op. A final
    fresh load (standing in for the real unlock -> reopen path) checks the
    generation guard blocks only that one superseded request, not every
    request after it.
    """
    request_started = asyncio.Event()
    hold = asyncio.Event()

    async def delay_status(route):
        request_started.set()
        await hold.wait()
        await route.continue_()

    await page.route("**/api/auth/status", delay_status)
    try:
        await _open_settings(page, base_url)
        await asyncio.wait_for(request_started.wait(), timeout=5)

        await page.evaluate(
            """async () => {
                const lock = await import('/static/app/lock.js');
                await lock.purgeRenderedData();
            }"""
        )
        assert await page.locator("#fp-auth-google-status").inner_text() == ""
        assert await page.locator("#fp-auth-apple-status").inner_text() == ""

        # Release the held response: the generation guard must make it a
        # no-op now that purge() already ran.
        hold.set()
        await page.wait_for_timeout(300)
        assert await page.locator("#fp-auth-google-status").inner_text() == ""
        assert await page.locator("#fp-auth-apple-status").inner_text() == ""
    finally:
        await page.unroute("**/api/auth/status", delay_status)

    # A fresh load after the purge -- the generation guard blocks only the
    # one superseded request, not every request after it (polling resumes
    # once mountAuthPanel/loadAuthStatus run again, i.e. after unlock).
    expected = (await _catalog(page, base_url))["auth"]["status"]["not_signed_in"]
    await page.evaluate(
        """async () => {
            const auth = await import('/static/app/auth.js');
            await auth.loadAuthStatus();
        }"""
    )
    await page.wait_for_function(
        "(text) => document.getElementById('fp-auth-google-status').textContent === text",
        arg=expected,
    )

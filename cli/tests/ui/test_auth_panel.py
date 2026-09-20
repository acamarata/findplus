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

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeout

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
    await page.goto(base_url + DASHBOARD)
    # openSettings() reads state.config for the About line and throws into its
    # own catch when the boot has not set it yet, so the dialog silently never
    # opens. Wait for the value it needs rather than for a wall-clock guess.
    await page.wait_for_function(
        "async () => (await import('/static/app/state.js')).state.config !== null"
    )
    # openSettings() swallows any failure into the alert banner and leaves the
    # dialog closed, so a bare wait_for_selector reports "hidden" and says
    # nothing about why. Click again once, then fail with what the banner says.
    for attempt in range(2):
        await page.click("#btn-settings")
        try:
            await page.wait_for_selector("#fp-settings-signin", timeout=10000)
            return
        except PlaywrightTimeout as timeout:
            if attempt:
                banner = await page.locator("#alert").inner_text()
                raise AssertionError(
                    f"Settings never opened; alert banner said: {banner!r}"
                ) from timeout


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
    """
    await _open_settings(page, base_url)
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

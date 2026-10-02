"""Sign-in card states that need the person to act (UAT #22) and their copy.

Purpose    : "Google signed Find+ out" used to be one muted line, the same weight
             as "Not signed in". The card now shows a boxed alert with its own
             "Sign in again" button; a signed-in, locked card says unlock is
             next; a signed-in, unlocked card says so. No browser or provider:
             status and helper/begin are stubbed.
"""

from __future__ import annotations

import pytest

from ._signin_helpers import open_settings_signin, reply, status_body, wait_text

pytestmark = pytest.mark.asyncio(loop_scope="session")

CARD = "#fp-auth-google-card"


async def test_revoked_is_an_alert_with_one_button_that_starts_the_sign_in(page, base_url):
    begins: list[str] = []
    await page.route("**/api/auth/google/helper/begin", reply({"browser": "chrome"}, 200, begins))
    await open_settings_signin(page, base_url, status_body(needs_g=["reauth"]))
    box = page.locator("#fp-auth-google-revoked")
    await box.wait_for(state="visible")
    assert await box.get_attribute("role") == "alert"
    assert "Google signed Find+ out" in await box.inner_text()
    assert await page.locator(CARD).get_attribute("data-attention") == "reauth"
    assert "Needs sign-in again" in await page.locator("#fp-auth-google-status").inner_text()
    # Only the attention box offers the sign-in; the plain button is out of the way.
    assert await page.locator("#fp-auth-google-hello").is_hidden()
    await page.locator("#fp-auth-google-revoked-btn").click()
    await wait_text(page, "#fp-auth-google-hello-status", "Finish signing in")
    assert len(begins) == 1


async def test_signed_out_is_not_flagged_as_needing_attention(page, base_url):
    await open_settings_signin(page, base_url, status_body())
    assert await page.locator("#fp-auth-google-revoked").is_hidden()
    assert await page.locator(CARD).get_attribute("data-attention") is None


async def test_signed_in_and_locked_points_at_the_unlock_step(page, base_url):
    await open_settings_signin(page, base_url, status_body(google=True, needs_g=["shared_key"]))
    assert await page.locator(CARD).get_attribute("data-attention") == "unlock"
    assert await page.locator("#fp-auth-google-unlock").is_visible()
    assert await page.locator("#fp-auth-google-ready").is_hidden()
    assert await page.locator("#fp-auth-google-revoked").is_hidden()


async def test_signed_in_and_unlocked_says_so_and_names_the_switch_cost(page, base_url):
    await open_settings_signin(page, base_url, status_body(google=True))
    assert await page.locator("#fp-auth-google-ready").is_visible()
    assert await page.locator(CARD).get_attribute("data-attention") is None
    hint = await page.locator("#fp-auth-google-switch-hint").inner_text()
    assert "unlock" in hint


async def test_disconnect_text_says_what_stops_and_what_stays(page, base_url):
    await open_settings_signin(page, base_url, status_body(google=True, apple=True))
    await page.locator("#fp-auth-google-disconnect").click()
    text = await page.locator("#fp-auth-google-disconnect-confirm").inner_text()
    assert "stops checking Google" in text
    assert "history stay on this computer" in text
    await page.locator("#fp-auth-google-disconnect-cancel").click()
    await page.locator("#fp-auth-apple-disconnect").click()
    text = await page.locator("#fp-auth-apple-disconnect-confirm").inner_text()
    assert "stops checking Apple" in text

"""The Google card's main path: sign in with your own Chrome, paste the token.

Purpose    : "Sign in with your Chrome" posts /api/auth/google/open, says which
             browser got the page, and reveals the numbered steps, the email
             and token fields and Connect. Connect posts /api/auth/google/token,
             empties the token field whatever the answer, and shows a refusal
             in the card. The separate-window option still starts the
             automatic flow, and the not-affiliated line stays.
Constraints: Every auth route is answered by page.route (the context-level
             /open stub in conftest.py is the backstop). No real browser, no
             provider, nothing written to the real ~/.findplus.
"""

from __future__ import annotations

import json

import pytest

from ._signin_helpers import (
    open_settings_signin,
    open_wizard_signin,
    reply,
    restore_onboarding,
    status_body,
    wait_text,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

TOKEN = "oauth2_4/ui-test-token"
PANEL = "#fp-auth-google-token-panel"
ERROR = "#fp-auth-google-connect-error"


async def _catalog(page, base_url) -> dict:
    response = await page.request.get(base_url + "/static/locales/en.json")
    return (await response.json())["signin"]["google"]


async def _open_panel(page, base_url, browser="chrome") -> list[str]:
    calls: list[str] = []
    await open_settings_signin(page, base_url)
    await page.route("**/api/auth/google/open", reply({"browser": browser, "url": "x"}, 200, calls))
    await page.get_by_role("button", name="Sign in with your Chrome").click()
    await page.locator(PANEL).wait_for(state="visible", timeout=15000)
    return calls


async def test_the_primary_button_opens_chrome_and_shows_the_steps(page, base_url):
    calls = await _open_panel(page, base_url)
    catalog = (await _catalog(page, base_url))["token"]

    assert len(calls) == 1
    await wait_text(page, "#fp-auth-google-opened", catalog["openedChrome"])
    steps = await page.locator("#fp-auth-google-steps li").all_inner_texts()
    assert steps == [catalog[f"step{n}"] for n in range(1, 6)]
    assert "Option+Command+I" in steps[1] and "oauth2_4/" in steps[3]
    assert await page.locator("#fp-auth-google-email").is_visible()
    assert await page.locator("#fp-auth-google-token").get_attribute("type") == "password"
    assert await page.locator("#fp-auth-google-connect").is_enabled()
    assert await page.locator("#fp-auth-not-affiliated").is_visible()


async def test_the_default_browser_is_named_when_chrome_was_not_used(page, base_url):
    await _open_panel(page, base_url, browser="default")
    catalog = (await _catalog(page, base_url))["token"]
    await wait_text(page, "#fp-auth-google-opened", catalog["openedDefault"])


async def test_connect_posts_the_token_and_the_card_shows_the_account(page, base_url):
    posted: list[dict] = []
    status = {"signed_in": False}

    async def token_route(route):
        posted.append(json.loads(route.request.post_data))
        status["signed_in"] = True
        await route.fulfill(json={"state": "done", "account": "g@example.com", "message": ""})

    async def status_route(route):
        await route.fulfill(json=status_body(google=status["signed_in"]))

    await _open_panel(page, base_url)
    await page.route("**/api/auth/status", status_route)
    await page.route("**/api/auth/google/token", token_route)
    await page.fill("#fp-auth-google-email", "g@example.com")
    await page.fill("#fp-auth-google-token", TOKEN)
    await page.locator("#fp-auth-google-connect").click()

    await wait_text(page, "#fp-auth-google-status", "Connected as g@example.com")
    assert posted == [{"email": "g@example.com", "oauth_token": TOKEN}]
    assert await page.locator(PANEL).is_hidden()
    assert await page.locator("#fp-auth-google-token").input_value() == ""


async def test_a_refused_token_is_shown_in_the_card_and_the_field_is_emptied(page, base_url):
    detail = "Google did not accept that token. It expires within minutes."
    await _open_panel(page, base_url)
    await page.route("**/api/auth/google/token", reply({"detail": detail}, 400))
    await page.fill("#fp-auth-google-email", "g@example.com")
    await page.fill("#fp-auth-google-token", TOKEN)
    await page.press("#fp-auth-google-token", "Enter")

    await wait_text(page, ERROR, detail)
    assert await page.locator("#fp-auth-google-token").input_value() == ""
    assert await page.locator("#fp-auth-google-connect").is_enabled()
    assert await page.locator(PANEL).is_visible()


async def test_empty_fields_are_named_and_nothing_is_sent(page, base_url):
    calls: list[str] = []
    await _open_panel(page, base_url)
    catalog = (await _catalog(page, base_url))["token"]
    await page.route("**/api/auth/google/token", reply({}, 200, calls))

    await page.locator("#fp-auth-google-connect").click()
    await wait_text(page, "#fp-auth-google-email-error", catalog["missingEmail"])
    await page.fill("#fp-auth-google-email", "g@example.com")
    await page.locator("#fp-auth-google-connect").click()
    await wait_text(page, "#fp-auth-google-token-error", catalog["missingToken"])
    assert calls == []


async def test_a_browser_that_cannot_open_still_shows_the_steps(page, base_url):
    await open_settings_signin(page, base_url)
    await page.route(
        "**/api/auth/google/open", reply({"detail": "Find+ could not open a browser."}, 503)
    )
    await page.get_by_role("button", name="Sign in with your Chrome").click()
    await wait_text(page, ERROR, "could not open a browser")
    assert await page.locator("#fp-auth-google-steps").is_visible()
    assert await page.locator("#fp-auth-google-opened").is_hidden()


async def test_the_separate_window_option_still_starts_the_automatic_flow(page, base_url):
    started: list[str] = []
    try:
        await open_wizard_signin(page, base_url)
        await page.route("**/api/auth/google/start", reply({"job_id": "job-1"}, 202, started))
        await page.route(
            "**/api/auth/google/progress*",
            reply({"chrome_found": True, "state": "waiting_for_user", "message": ""}),
        )
        await page.get_by_role("button", name="Or let Find+ open its own Chrome window").click()
        await wait_text(page, "#fp-setup-google-progress", "Finish signing in")
        assert len(started) == 1
        assert await page.locator("#fp-setup-google-token-panel").is_hidden()
        assert await page.locator("#fp-setup-not-affiliated").is_visible()
    finally:
        await restore_onboarding(page, base_url)

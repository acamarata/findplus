"""Apple sign-in states, and the same component inside Settings (E14).

Purpose    : The Apple card walks Apple ID + password -> a 2FA code -> signed
             in, and every way that can stop: missing fields, a refused start,
             a wrong code, and an install without the Apple extra
             (`needs: ["apple_extra"]`), which now gets a plain explanation in
             place of a form that could only fail. The last tests check that
             Settings > Sign-in mounts the very same component, so a failure
             there is shown in the card with Retry, never swallowed.
Constraints: Every auth route is answered by page.route: no Apple account, no
             network, nothing written to the real ~/.findplus.
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

CONNECT = "Connect Apple Find My"
ERROR = "#fp-setup-apple-error"


async def _catalog(page, base_url) -> dict:
    response = await page.request.get(base_url + "/static/locales/en.json")
    return (await response.json())["signin"]


async def _submit_credentials(page) -> None:
    await page.fill("#fp-setup-apple-id", "a@example.com")
    await page.fill("#fp-setup-apple-password", "not-a-real-password")
    await page.get_by_role("button", name=CONNECT).click()


async def _to_code_step(page) -> None:
    await page.route("**/api/auth/apple/start", reply({"job_id": "apple-1"}, 202))
    await page.route(
        "**/api/auth/apple/progress*",
        reply({"state": "needs_2fa", "message": "Enter the code from your trusted device."}),
    )
    await _submit_credentials(page)
    await page.locator("#fp-setup-apple-2fa").wait_for(state="visible", timeout=15000)


async def test_missing_fields_are_named_inline_without_failing_the_card(page, base_url):
    """UAT6 N22: an empty Apple ID or password used to raise the full failed
    state (a red card border, "Sign-in did not finish", Try again). It is now
    a plain field error, and the card never leaves `data-state="idle"`."""
    calls: list[str] = []
    try:
        await open_wizard_signin(page, base_url)
        catalog = await _catalog(page, base_url)
        await page.route("**/api/auth/apple/start", reply({"job_id": "x"}, 202, calls))
        await page.get_by_role("button", name=CONNECT).click()
        await wait_text(page, "#fp-setup-apple-id-error", catalog["apple"]["missingAppleId"])
        await wait_text(page, "#fp-setup-apple-password-error", catalog["apple"]["missingPassword"])
        assert calls == []
        assert await page.locator(ERROR).is_hidden()
        assert await page.locator("#fp-setup-apple-card").get_attribute("data-state") != "failed"

        # Filling one field and retrying clears both -- retyping, not a
        # second click, is what should make a stale error go away.
        await page.fill("#fp-setup-apple-id", "a@example.com")
        assert await page.locator("#fp-setup-apple-id-error").is_hidden()
        assert await page.locator("#fp-setup-apple-password-error").is_hidden()
    finally:
        await restore_onboarding(page, base_url)


async def test_the_code_step_then_signed_in(page, base_url):
    code_bodies: list[dict] = []

    async def code_route(route):
        code_bodies.append(json.loads(route.request.post_data))
        await route.fulfill(json={"state": "done", "message": "Authenticated as a@example.com."})

    try:
        await open_wizard_signin(page, base_url)
        await _to_code_step(page)
        assert await page.locator("#fp-setup-apple-password").input_value() == ""
        assert await page.locator("#fp-setup-apple-form").is_hidden()

        await page.route("**/api/auth/apple/code", code_route)
        await page.unroute("**/api/auth/status")
        await page.route("**/api/auth/status", reply(status_body(apple=True)))
        await page.fill("#fp-setup-apple-code", "123456")
        await page.get_by_role("button", name="Verify code").click()

        await wait_text(page, "#fp-setup-apple-status", "Signed in as a@example.com")
        assert code_bodies == [{"job_id": "apple-1", "code": "123456"}]
        assert await page.locator("#fp-setup-apple-2fa").is_hidden()
        assert await page.get_by_role("button", name="Use a different Apple ID").is_visible()
    finally:
        await restore_onboarding(page, base_url)


async def test_a_wrong_code_is_named_and_the_code_field_stays(page, base_url):
    try:
        await open_wizard_signin(page, base_url)
        catalog = await _catalog(page, base_url)
        await _to_code_step(page)
        await page.route(
            "**/api/auth/apple/code", reply({"detail": "invalid or expired code"}, 400)
        )
        await page.fill("#fp-setup-apple-code", "000000")
        await page.get_by_role("button", name="Verify code").click()
        await wait_text(page, ERROR, catalog["error"]["badCode"])
        assert await page.locator("#fp-setup-apple-2fa").is_visible()
        assert await page.locator("#fp-setup-apple-code").input_value() == ""
    finally:
        await restore_onboarding(page, base_url)


async def test_a_failed_apple_job_shows_why_and_retry_goes_back_to_the_form(page, base_url):
    try:
        await open_wizard_signin(page, base_url)
        await page.route("**/api/auth/apple/start", reply({"job_id": "apple-2"}, 202))
        await page.route(
            "**/api/auth/apple/progress*", reply({"state": "failed", "message": "Bad password."})
        )
        await _submit_credentials(page)
        await wait_text(page, ERROR, "Bad password.")
        await page.locator(ERROR).get_by_role("button", name="Try again").click()
        assert await page.locator(ERROR).is_hidden()
        assert await page.locator("#fp-setup-apple-form").is_visible()
    finally:
        await restore_onboarding(page, base_url)


async def test_no_apple_extra_explains_instead_of_a_dead_form(page, base_url):
    try:
        await open_wizard_signin(page, base_url, status_body(needs_a=["apple_extra"]))
        catalog = await _catalog(page, base_url)
        await wait_text(page, "#fp-setup-apple-unavailable", catalog["apple"]["unavailable"])
        assert await page.locator("#fp-setup-apple-form").is_hidden()
        assert await page.get_by_role("button", name=CONNECT).is_hidden()
    finally:
        await restore_onboarding(page, base_url)


async def test_a_503_on_start_switches_to_the_explanation(page, base_url):
    try:
        await open_wizard_signin(page, base_url)
        await page.route(
            "**/api/auth/apple/start",
            reply({"detail": "Apple provider not installed. pip install 'findplus[apple]'"}, 503),
        )
        await _submit_credentials(page)
        await page.locator("#fp-setup-apple-unavailable").wait_for(state="visible")
        assert await page.locator("#fp-setup-apple-form").is_hidden()
    finally:
        await restore_onboarding(page, base_url)


async def test_settings_shows_a_refused_start_with_retry(page, base_url):
    await open_settings_signin(page, base_url)
    await page.route("**/api/auth/google/start", reply({"detail": "Internal Server Error"}, 500))
    await page.click("#fp-auth-google-signin")
    await wait_text(page, "#fp-auth-google-error", "could not start the sign-in")
    retry = page.locator("#fp-auth-google-error").get_by_role("button", name="Try again")
    assert await retry.is_visible()


async def test_settings_hides_the_apple_form_and_key_upload_without_the_extra(page, base_url):
    await open_settings_signin(page, base_url, status_body(needs_a=["apple_extra"]))
    await page.locator("#fp-auth-apple-unavailable").wait_for(state="visible")
    assert await page.locator("#fp-auth-apple-form").is_hidden()
    assert await page.locator("#fp-auth-apple-accessories").is_hidden()

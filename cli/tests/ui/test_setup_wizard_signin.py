"""The wizard's sign-in step rejoins a sign-in that is already running.

Purpose    : `POST /api/auth/google/start` answers 409 with the job_id of the
             run already in progress rather than opening a second Chrome.
             api.js used to drop that body, so a caller could report the
             conflict and nothing else (CR-C-E10 F1). This pins that the id
             survives the error and that the step polls that exact job.
Constraints: Nothing real is started: both auth routes are intercepted, so no
             browser launches and no provider is contacted.
Ticket     : P2-E11-W4-S1-T7.
"""

from __future__ import annotations

import json

import pytest

from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")

RUNNING_JOB = "job-already-running"


async def _set_completed_at(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.completed_at",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def _set_last_step(page, base_url, value):
    await page.request.post(
        base_url + "/api/settings/onboarding.last_step",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def test_step_has_a_heading_and_google_button_reflects_signed_in_state(
    page, base_url
) -> None:
    """UAT U33: step 2 had no heading at all, and the Google button still
    offered a fresh sign-in after the status line above it already said
    "Signed in as...". The button's own label now carries that state too
    ("Switch Google account" since the E14 shared sign-in cards)."""

    async def status_signed_in(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "providers": [
                        {
                            "id": "google-find-hub",
                            "signed_in": True,
                            "account": "someone@example.com",
                            "needs": [],
                        }
                    ]
                }
            ),
        )

    await _set_completed_at(page, base_url, None)
    try:
        await _set_last_step(page, base_url, "signin")
        await page.route("**/api/auth/status", status_signed_in)
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("#fp-setup-signin-status", timeout=15000)

        # text_content(), not inner_text(): h2 is styled text-transform:
        # uppercase, which inner_text() would reflect as "SIGN IN".
        assert (await page.locator("#setup-view h2").first.text_content()) == (
            "Connect your trackers"
        )
        await page.wait_for_function(
            "() => document.getElementById('fp-setup-signin-status')"
            ".textContent.includes('Signed in as')",
            timeout=15000,
        )
        button = page.get_by_role("button", name="Switch Google account")
        await button.wait_for(state="visible")
        assert await button.is_enabled()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_a_409_rejoins_the_running_sign_in(page, base_url):
    polled: list[str] = []

    async def conflict(route):
        await route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps(
                {"detail": "A Google sign-in is already in progress.", "job_id": RUNNING_JOB}
            ),
        )

    async def progress(route):
        polled.append(route.request.url)
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"state": "waiting_for_user", "message": "in the Chrome window"}),
        )

    await _set_completed_at(page, base_url, None)
    try:
        await _set_last_step(page, base_url, "signin")
        await page.route("**/api/auth/google/start", conflict)
        await page.route("**/api/auth/google/progress*", progress)
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("#fp-setup-signin-status", timeout=15000)

        await page.get_by_role("button", name="Connect Google Find Hub").click()
        await page.wait_for_function(
            "() => document.getElementById('fp-setup-google-progress')"
            ".textContent.includes('Finish signing in')",
            timeout=15000,
        )

        assert polled, "the conflict was reported but the running job was never rejoined"
        assert RUNNING_JOB in polled[0]
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


def _status_body(*, signed_in: bool, needs: list[str]) -> dict:
    return {
        "providers": [
            {
                "id": "google-find-hub",
                "signed_in": signed_in,
                "account": "someone@example.com" if signed_in else None,
                "needs": needs,
            }
        ]
    }


async def test_signed_in_hides_the_chrome_notice_even_with_a_stale_needs_chrome(
    page, base_url
) -> None:
    """UAT3 N20: the wizard's ChromeGate checked `needs` alone, so a
    signed-in account with a stale `needs: ["chrome"]` still showed "Google
    Chrome was not found..." under the switch-account button. It now
    shares provider_chrome.js's googleChromeNoticeNeeded() with Settings'
    own gate (auth.js renderGoogleCard, UAT2 N1), which already gated on
    `!signed_in`."""

    async def status(route):
        await route.fulfill(json=_status_body(signed_in=True, needs=["chrome"]))

    await _set_completed_at(page, base_url, None)
    try:
        await _set_last_step(page, base_url, "signin")
        await page.route("**/api/auth/status", status)
        await page.goto(base_url + "/#/setup")
        # wait_for_selector first: wait_for_function's predicate throws on a
        # null element rather than retrying past it (unlike wait_for_selector,
        # which polls for attachment), so calling it before the element exists
        # surfaces "Cannot read properties of null" instead of a clean
        # timeout -- same ordering test_step_has_a_heading_... above uses.
        await page.wait_for_selector("#fp-setup-signin-status", timeout=15000)
        await page.wait_for_function(
            "() => document.getElementById('fp-setup-signin-status')"
            ".textContent.includes('Signed in as')",
            timeout=15000,
        )

        assert await page.locator("#fp-setup-chrome-notice").is_hidden()
        button = page.get_by_role("button", name="Switch Google account")
        assert await button.is_enabled()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_signed_out_and_chrome_missing_shows_the_notice(page, base_url) -> None:
    """The one state where the notice must actually appear, same gate as
    Settings' own chrome-missing case (test_auth_chrome_notice.py)."""

    async def status(route):
        await route.fulfill(json=_status_body(signed_in=False, needs=["chrome"]))

    await _set_completed_at(page, base_url, None)
    try:
        await _set_last_step(page, base_url, "signin")
        await page.route("**/api/auth/status", status)
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("#fp-setup-signin-status", timeout=15000)
        await page.wait_for_function(
            "() => document.getElementById('fp-setup-signin-status')"
            ".textContent.includes('Not signed in')",
            timeout=15000,
        )

        assert await page.locator("#fp-setup-chrome-notice").is_visible()
        button = page.get_by_role("button", name="Connect Google Find Hub")
        assert not await button.is_enabled()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)

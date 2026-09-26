"""Browser tests for the wizard's sign-in step and the Chrome-missing notice
(T0 addendum B5, loop2 B1).

Split out of test_setup_wizard_notifications.py (2026-09-26, PRI rule-7 size
cap): that file crossed the 300-line ceiling once WP-B's own `chromeNoticeText()`
fix (cards.js, commit d3e2215) needed a matching regex here to derive the
notice's actual rendered text instead of the full honesty.py sentence.
"""

from __future__ import annotations

import json
import re

import pytest

from findplus.honesty import CHROME_REQUIRED

from .conftest import SEEDED_COMPLETED_AT

# cards.js's chromeNoticeText() strips CHROME_REQUIRED's trailing "Install
# it from <url> and try again" clause: the download link beside it already
# carries that URL (WP-B, commit d3e2215). Same regex, so this asserts the
# actual rendered text.
CHROME_NOTICE = re.sub(r"\s*Install it from https?://\S+ and try again\.?\s*$", "", CHROME_REQUIRED)

pytestmark = pytest.mark.asyncio(loop_scope="session")


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


async def _open_step(page, base_url, step):
    await _set_completed_at(page, base_url, None)
    await _set_last_step(page, base_url, step)
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#setup-view .fp-wizard-step", timeout=15000)


async def test_signin_step_shows_chrome_notice_before_any_click(page, base_url):
    """T0 addendum B5: GET /api/auth/status's `needs: ["chrome"]` (already
    computed by providers/auth_status.py) is read on entry, not only after a
    failed click, and the Google button is disabled while it applies."""

    async def status_route(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "providers": [
                        {
                            "id": "google-find-hub",
                            "signed_in": False,
                            "account": None,
                            "needs": ["chrome"],
                        }
                    ]
                }
            ),
        )

    try:
        await page.route("**/api/auth/status", status_route)
        await _open_step(page, base_url, "signin")
        await page.wait_for_selector("#fp-setup-chrome-notice:not([hidden])", timeout=15000)
        assert await page.locator("#fp-setup-chrome-notice").inner_text() == CHROME_NOTICE
        assert await page.get_by_role("button", name="Connect Google Find Hub").is_disabled()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_signin_step_maps_a_400_to_the_honesty_sentence_not_raw_text(page, base_url):
    """T0 addendum B5: the route's only 400 is ChromeNotFoundError, but this
    never trusts the thrown message's text — it renders the live notice."""

    async def start_route(route):
        # Deliberately NOT honesty.CHROME_REQUIRED's text, to prove the UI
        # does not just echo whatever the 400 body happens to say.
        await route.fulfill(
            status=400,
            content_type="application/json",
            body=json.dumps({"detail": "ChromeNotFoundError: no chrome binary on PATH"}),
        )

    try:
        await _open_step(page, base_url, "signin")
        await page.route("**/api/auth/google/start", start_route)
        await page.get_by_role("button", name="Connect Google Find Hub").click()
        await page.wait_for_selector("#fp-setup-chrome-notice:not([hidden])", timeout=15000)
        notice = await page.locator("#fp-setup-chrome-notice").inner_text()
        assert notice == CHROME_NOTICE
        assert "ChromeNotFoundError" not in notice
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)


async def test_signin_step_clears_status_line_on_chrome_missing_400(page, base_url):
    """loop2 B1: the status line must not keep reading "Starting Chrome..."
    once the Chrome-missing notice is showing -- that pairs a "please wait"
    message with a "this cannot proceed" one, a contradictory UI state."""

    async def start_route(route):
        await route.fulfill(
            status=400,
            content_type="application/json",
            body=json.dumps({"detail": "ChromeNotFoundError: no chrome binary on PATH"}),
        )

    try:
        await _open_step(page, base_url, "signin")
        await page.route("**/api/auth/google/start", start_route)
        await page.get_by_role("button", name="Connect Google Find Hub").click()
        await page.wait_for_selector("#fp-setup-chrome-notice:not([hidden])", timeout=15000)
        # The in-progress line (E14: one per card) is gone, not left reading
        # "Opening Chrome..." beside a notice that says Chrome is missing.
        assert await page.locator("#fp-setup-google-progress").is_hidden()
    finally:
        await _set_completed_at(page, base_url, SEEDED_COMPLETED_AT)
        await _set_last_step(page, base_url, None)

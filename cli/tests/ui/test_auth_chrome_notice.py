"""Browser tests for the Chrome-missing notice gating (UAT2 N1).

143fb48/43dca29 fixed Settings > Sign-in always showing "Google Chrome was
not found" with a download link, even when signed in and Chrome installed.
The shared Google flow (web/app/signin/google_flow.js, E14) shows
#fp-auth-chrome-notice and #fp-auth-chrome-download only when GET
/api/auth/status's `needs` names "chrome" AND the account is not signed in;
both are built hidden. These tests stub that endpoint with page.route (the same
technique test_auth_panel.py's
test_in_flight_status_response_does_not_repopulate_after_purge uses) so the
three gating states are deterministic, independent of whether the machine
running the suite actually has Chrome installed.
"""

from __future__ import annotations

import pytest

from .test_auth_panel import _open_settings

pytestmark = pytest.mark.asyncio(loop_scope="session")

_NOW = "2026-01-01T00:00:00+00:00"


def _auth_status_body(*, signed_in: bool, needs: list[str], account: str | None = None) -> dict:
    """A GET /api/auth/status body shaped like providers/auth_status.py's
    build_auth_status(), with the Apple card left at its default (signed out,
    nothing needed) since only the Google card's gating is under test here."""
    return {
        "providers": [
            {
                "id": "google-find-hub",
                "signed_in": signed_in,
                "account": account,
                "method": "chrome",
                "last_checked": _NOW,
                "needs": needs,
            },
            {
                "id": "apple-find-my",
                "signed_in": False,
                "account": None,
                "method": "apple-2fa",
                "last_checked": _NOW,
                "needs": [],
            },
        ]
    }


async def _open_settings_with_status(page, base_url, body: dict) -> None:
    """Stub /api/auth/status with `body`, then open Settings and wait for the
    Google card to actually render it (the status line starts empty in the
    markup, so a non-empty textContent proves the stubbed response landed)."""

    async def fulfill(route):
        await route.fulfill(json=body)

    await page.route("**/api/auth/status", fulfill)
    await _open_settings(page, base_url)
    await page.wait_for_function(
        "() => document.getElementById('fp-auth-google-status').textContent !== ''"
    )


async def test_chrome_found_not_signed_in_hides_notice_and_link(page, base_url) -> None:
    """Chrome present, signed out: `needs` is empty, so nothing shows."""
    body = _auth_status_body(signed_in=False, needs=[])
    await _open_settings_with_status(page, base_url, body)

    assert await page.locator("#fp-auth-chrome-notice").is_hidden()
    assert await page.locator("#fp-auth-chrome-download").is_hidden()


async def test_signed_in_hides_notice_even_if_chrome_detection_fails(page, base_url) -> None:
    """Signed in with a stale/incorrect `needs: ["chrome"]`: the flow
    gates on `!signed_in`, so an already-signed-in account never sees it."""
    body = _auth_status_body(signed_in=True, needs=["chrome"], account="someone@example.com")
    await _open_settings_with_status(page, base_url, body)

    assert await page.locator("#fp-auth-chrome-notice").is_hidden()
    assert await page.locator("#fp-auth-chrome-download").is_hidden()


async def test_chrome_missing_and_signed_out_shows_notice_and_link(page, base_url) -> None:
    """The one state where both must actually be visible."""
    body = _auth_status_body(signed_in=False, needs=["chrome"])
    await _open_settings_with_status(page, base_url, body)

    assert await page.locator("#fp-auth-chrome-notice").is_visible()
    assert await page.locator("#fp-auth-chrome-download").is_visible()
    assert await page.locator("#fp-auth-google-signin").is_disabled()

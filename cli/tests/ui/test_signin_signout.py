"""Sign out / disconnect a provider (S11/WP8, gap-audit-2026-09-26).

Purpose    : Each signed-in card gets a "Disconnect" button behind an inline
             confirm row (never `window.confirm`), on both the wizard's
             sign-in step and Settings > Sign-in, that calls `DELETE
             /api/auth/{provider}` and then re-reads status. Every auth route
             is answered by page.route: no real Google/Apple account, no
             network, nothing written to the real ~/.findplus.
"""

from __future__ import annotations

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


async def _delete_route(route, calls: list[str]) -> None:
    assert route.request.method == "DELETE"
    calls.append(route.request.url)
    await route.fulfill(status=204)


async def test_disconnect_hidden_until_signed_in(page, base_url):
    try:
        await open_wizard_signin(page, base_url, status_body(google=False, apple=False))
        assert await page.locator("#fp-setup-google-disconnect").is_hidden()
        assert await page.locator("#fp-setup-apple-disconnect").is_hidden()
    finally:
        await restore_onboarding(page, base_url)


async def test_google_disconnect_confirm_row_and_cancel(page, base_url):
    """Clicking Disconnect shows the inline confirm row (never window.confirm);
    clicking its own Cancel backs out without any request."""
    calls: list[str] = []
    try:
        await open_wizard_signin(page, base_url, status_body(google=True))
        await page.route("**/api/auth/google-find-hub", lambda r: _delete_route(r, calls))

        await page.click("#fp-setup-google-disconnect")
        confirm_row = page.locator("#fp-setup-google-disconnect-confirm")
        assert await confirm_row.is_visible()
        assert await page.locator("#fp-setup-google-disconnect").is_hidden()
        await wait_text(
            page, "#fp-setup-google-disconnect-confirm", "Tracked devices and their history stay"
        )

        await page.click("#fp-setup-google-disconnect-cancel")
        assert await confirm_row.is_hidden()
        assert await page.locator("#fp-setup-google-disconnect").is_visible()
        assert calls == []
    finally:
        await restore_onboarding(page, base_url)


async def test_google_disconnect_confirmed_calls_delete_and_re_reads_status(page, base_url):
    calls: list[str] = []
    try:
        await open_wizard_signin(page, base_url, status_body(google=True))
        await page.route("**/api/auth/google-find-hub", lambda r: _delete_route(r, calls))
        await page.unroute("**/api/auth/status")
        await page.route("**/api/auth/status", reply(status_body(google=False)))

        await page.click("#fp-setup-google-disconnect")
        await page.click("#fp-setup-google-disconnect-yes")

        await wait_text(page, "#fp-setup-google-status", "Not signed in")
        assert len(calls) == 1
        assert calls[0].endswith("/api/auth/google-find-hub")
        assert await page.locator("#fp-setup-google-disconnect-confirm").is_hidden()
        assert await page.locator("#fp-setup-google-disconnect").is_hidden()
    finally:
        await restore_onboarding(page, base_url)


async def test_apple_disconnect_confirmed_calls_delete_and_re_reads_status(page, base_url):
    calls: list[str] = []
    try:
        await open_wizard_signin(page, base_url, status_body(apple=True))
        await page.route("**/api/auth/apple-find-my", lambda r: _delete_route(r, calls))
        await page.unroute("**/api/auth/status")
        await page.route("**/api/auth/status", reply(status_body(apple=False)))

        await page.click("#fp-setup-apple-disconnect")
        await page.click("#fp-setup-apple-disconnect-yes")

        await wait_text(page, "#fp-setup-apple-status", "Not signed in")
        assert len(calls) == 1
        assert calls[0].endswith("/api/auth/apple-find-my")
    finally:
        await restore_onboarding(page, base_url)


async def test_settings_disconnect_mounts_the_same_control(page, base_url):
    """Settings > Sign-in is the same shared component (panel.js), so the
    Disconnect flow works there too, not only in the wizard."""
    calls: list[str] = []
    try:
        await open_settings_signin(page, base_url, status_body(google=True))
        await page.route("**/api/auth/google-find-hub", lambda r: _delete_route(r, calls))
        await page.unroute("**/api/auth/status")
        await page.route("**/api/auth/status", reply(status_body(google=False)))

        await page.click("#fp-auth-google-disconnect")
        await page.click("#fp-auth-google-disconnect-yes")

        await wait_text(page, "#fp-auth-google-status", "Not signed in")
        assert len(calls) == 1
    finally:
        await restore_onboarding(page, base_url)


async def test_a_failed_disconnect_is_shown_not_swallowed(page, base_url):
    try:
        await open_wizard_signin(page, base_url, status_body(google=True))
        await page.route(
            "**/api/auth/google-find-hub",
            lambda r: r.fulfill(status=500, json={"detail": "Internal Server Error"}),
        )

        await page.click("#fp-setup-google-disconnect")
        await page.click("#fp-setup-google-disconnect-yes")

        await wait_text(page, "#fp-setup-google-error", "Internal Server Error")
        assert await page.locator("#fp-setup-google-disconnect-confirm").is_hidden()
    finally:
        await restore_onboarding(page, base_url)

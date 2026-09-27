"""The Google card's "Unlock encrypted locations" step (Part 3 UI).

Purpose    : The block shows only when the account is signed in but its E2EE
             key is still locked (`needs` includes `shared_key`). Its button
             posts /api/auth/google/unlock/start, progress is shown, done hides
             the block, a failure is shown in it, and the honest explanation
             (own Chrome window, screen lock once, never paste code) is present.
Constraints: Every route answered by page.route; no browser, no vendor.
"""

from __future__ import annotations

import pytest

from ._signin_helpers import open_settings_signin, reply, status_body, wait_text

pytestmark = pytest.mark.asyncio(loop_scope="session")

BLOCK = "#fp-auth-google-unlock"
STATUS = "#fp-auth-google-unlock-status"
ERROR = "#fp-auth-google-unlock-error"


async def _open_locked(page, base_url):
    """Settings sign-in, Google signed in but E2EE locked (needs shared_key)."""
    await open_settings_signin(page, base_url, status_body(google=True, needs_g=["shared_key"]))
    await page.locator(BLOCK).wait_for(state="visible", timeout=15000)


async def test_the_block_shows_the_honest_explanation_and_button(page, base_url):
    await _open_locked(page, base_url)
    why = await page.locator("#fp-auth-google-unlock .fp-signin-how").first.inner_text()
    assert "end to end" in why
    assert "screen lock" in why
    assert "never asks you to paste code" in why
    assert await page.get_by_role("button", name="Unlock encrypted locations").is_visible()


async def test_the_block_is_hidden_when_not_locked(page, base_url):
    await open_settings_signin(page, base_url, status_body(google=True))
    assert await page.locator(BLOCK).is_hidden()


async def test_unlock_posts_start_shows_progress_then_hides_when_done(page, base_url):
    started: list[str] = []
    state = {"locked": True}

    async def status_route(route):
        body = status_body(google=True, needs_g=["shared_key"] if state["locked"] else [])
        await route.fulfill(json=body)

    async def progress_route(route):
        state["locked"] = False  # the key is stored; the next status is unlocked
        await route.fulfill(json={"state": "done", "message": "Encrypted locations unlocked."})

    await _open_locked(page, base_url)
    await page.unroute("**/api/auth/status")
    await page.route("**/api/auth/status", status_route)
    await page.route("**/api/auth/google/unlock/start", reply({"job_id": "u1"}, 202, started))
    await page.route("**/api/auth/google/unlock/progress*", progress_route)

    await page.get_by_role("button", name="Unlock encrypted locations").click()
    await page.locator(BLOCK).wait_for(state="hidden", timeout=15000)
    assert len(started) == 1


async def test_a_waiting_state_is_shown(page, base_url):
    await _open_locked(page, base_url)
    await page.route("**/api/auth/google/unlock/start", reply({"job_id": "u1"}, 202))
    await page.route(
        "**/api/auth/google/unlock/progress*",
        reply({"state": "waiting_for_user", "message": "Enter your Android phone's screen lock."}),
    )
    await page.get_by_role("button", name="Unlock encrypted locations").click()
    await wait_text(page, STATUS, "Android phone's screen lock")
    assert await page.locator("#fp-auth-google-unlock-cancel").is_visible()


async def test_a_failed_start_is_shown_in_the_block(page, base_url):
    await _open_locked(page, base_url)
    await page.route(
        "**/api/auth/google/unlock/start", reply({"detail": "Internal Server Error"}, 500)
    )
    await page.get_by_role("button", name="Unlock encrypted locations").click()
    await wait_text(page, ERROR, "Internal Server Error")
    assert await page.locator(BLOCK).is_visible()

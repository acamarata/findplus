"""The unlock step offers the helper when the helper is detected.

Purpose    : with `google_helper_installed` the primary Unlock button posts
             /api/auth/google/helper/unlock-begin (Google's unlock page in the
             user's own Chrome) and watches status until the lock clears; the
             separate Chrome window is the "other way". Without the helper the
             old own-window flow is unchanged. A failed hand-off is shown in
             the block. No real browser: every route is stubbed.
"""

from __future__ import annotations

import pytest

from ._signin_helpers import reply, status_body, wait_text

pytestmark = pytest.mark.asyncio(loop_scope="session")

BLOCK = "#fp-auth-google-unlock"
OWN = "#fp-auth-google-unlock-own"
ERROR = "#fp-auth-google-unlock-error"
STATUS = "#fp-auth-google-unlock-status"


def _body(*, installed: bool, locked: bool = True, outcome=None) -> dict:
    body = status_body(google=True, needs_g=["shared_key"] if locked else [])
    body["google_helper_installed"] = installed
    body["google_helper_outcome"] = outcome
    return body


async def _open(page, base_url, state: dict) -> None:
    async def status_route(route):
        await route.fulfill(json=_body(**state))

    await page.add_init_script("window.__FP_TEST_STATUS_POLL_MS__ = 40;")
    await page.route("**/api/auth/status", status_route)
    await page.goto(base_url + "/#dashboard")
    await page.click("#btn-settings")
    await page.locator(BLOCK).wait_for(state="visible", timeout=15000)


async def test_with_the_helper_the_button_uses_it_and_the_block_clears(page, base_url):
    state = {"installed": True}
    begun, own = [], []

    async def begin_route(route):
        begun.append(1)
        state["locked"] = False  # the helper posts the key; the lock clears
        await route.fulfill(status=202, json={"browser": "chrome", "generation": 0})

    await _open(page, base_url, state)
    await page.route("**/api/auth/google/helper/unlock-begin", begin_route)
    await page.route("**/api/auth/google/unlock/start", reply({"job_id": "x"}, 202, own))
    why = await page.locator("#fp-auth-google-unlock .fp-signin-how").first.inner_text()
    assert "Find+ helper" in why
    assert await page.locator(OWN).is_visible()
    await page.get_by_role("button", name="Unlock encrypted locations").click()
    await page.locator(BLOCK).wait_for(state="hidden", timeout=15000)
    assert begun == [1] and own == []


async def test_other_way_still_runs_the_separate_window_flow(page, base_url):
    started, begun = [], []
    await _open(page, base_url, {"installed": True})
    await page.route("**/api/auth/google/unlock/start", reply({"job_id": "u1"}, 202, started))
    await page.route(
        "**/api/auth/google/unlock/progress*",
        reply({"state": "waiting_for_user", "message": "Enter your screen lock."}),
    )
    await page.route("**/api/auth/google/helper/unlock-begin", reply({}, 202, begun))
    await page.locator(OWN).click()
    await wait_text(page, STATUS, "Enter your screen lock.")
    assert len(started) == 1 and begun == []


async def test_without_the_helper_nothing_changes(page, base_url):
    await _open(page, base_url, {"installed": False})
    assert await page.locator(OWN).is_hidden()
    why = await page.locator("#fp-auth-google-unlock .fp-signin-how").first.inner_text()
    assert "Chrome window of its own" in why


async def test_a_failed_hand_off_is_shown_in_the_block(page, base_url):
    state = {"installed": True}

    async def begin_route(route):
        state["outcome"] = {"kind": "unlock", "ok": False, "message": "No key came back."}
        await route.fulfill(status=202, json={"browser": "chrome", "generation": 0})

    await _open(page, base_url, state)
    await page.route("**/api/auth/google/helper/unlock-begin", begin_route)
    await page.get_by_role("button", name="Unlock encrypted locations").click()
    await wait_text(page, ERROR, "No key came back.")
    assert await page.locator(BLOCK).is_visible()


async def test_a_failed_begin_is_shown_in_the_block(page, base_url):
    await _open(page, base_url, {"installed": True})
    await page.route(
        "**/api/auth/google/helper/unlock-begin", reply({"detail": "No browser."}, 503)
    )
    await page.get_by_role("button", name="Unlock encrypted locations").click()
    await wait_text(page, ERROR, "No browser.")

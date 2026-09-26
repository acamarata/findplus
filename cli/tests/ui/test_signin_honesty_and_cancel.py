"""UAT6 N08 (not-affiliated on every card) and N23 (Cancel while waiting).

Purpose    : N08 -- cards.js's header long claimed every sign-in card said
             "not affiliated with Google/Apple"; it only ever showed on
             Welcome and Settings > Notices. Both cards on both surfaces now
             render it themselves. N23 -- there was no way to back out of
             "waiting on Chrome" short of closing the window; a Cancel button
             does now, calling POST /api/auth/google/cancel.
Constraints: Every auth route is answered by page.route; no real Chrome, no
             network, nothing written to the real ~/.findplus.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from ._signin_helpers import open_settings_signin, open_wizard_signin, reply, restore_onboarding

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _catalog_honesty(page, base_url) -> str:
    response = await page.request.get(base_url + "/static/locales/en.json")
    return (await response.json())["honesty"]["notAffiliated"]


# --------------------------------------------------------------------- N08
async def test_not_affiliated_sentence_on_both_wizard_cards(page, base_url):
    try:
        await open_wizard_signin(page, base_url)
        sentence = await _catalog_honesty(page, base_url)
        await wait_text_local(page, "#fp-setup-google-not-affiliated", sentence)
        await wait_text_local(page, "#fp-setup-apple-not-affiliated", sentence)
    finally:
        await restore_onboarding(page, base_url)


async def test_not_affiliated_sentence_on_both_settings_cards(page, base_url):
    await open_settings_signin(page, base_url)
    sentence = await _catalog_honesty(page, base_url)
    await wait_text_local(page, "#fp-auth-google-not-affiliated", sentence)
    await wait_text_local(page, "#fp-auth-apple-not-affiliated", sentence)


async def wait_text_local(page, selector: str, text: str) -> None:
    await page.locator(selector, has_text=text).wait_for(state="visible", timeout=15000)


# --------------------------------------------------------------------- N23
async def test_cancel_while_waiting_on_chrome(page, base_url):
    """Cancel stops the local wait and tells the daemon to end the job."""
    cancel_calls: list[dict] = []

    async def cancel_route(route):
        cancel_calls.append(json.loads(route.request.post_data))
        await route.fulfill(json={"state": "failed", "message": "Sign-in cancelled."})

    try:
        await open_wizard_signin(page, base_url)
        await page.route("**/api/auth/google/start", reply({"job_id": "job-cancel"}, 202))
        await page.route(
            "**/api/auth/google/progress*",
            reply({"chrome_found": True, "state": "waiting_for_user", "message": ""}),
        )
        await page.route("**/api/auth/google/cancel", cancel_route)

        await page.get_by_role("button", name="Connect Google Find Hub").click()
        await page.locator("#fp-setup-google-cancel").wait_for(state="visible", timeout=15000)

        await page.click("#fp-setup-google-cancel")

        assert await page.get_by_role("button", name="Connect Google Find Hub").is_enabled()
        assert await page.locator("#fp-setup-google-progress").is_hidden()
        assert cancel_calls == [{"job_id": "job-cancel"}]
    finally:
        await restore_onboarding(page, base_url)


async def test_cancel_before_the_job_id_is_known_still_ends_the_wait(page, base_url):
    """The Cancel click can land while POST /start is still in flight."""
    held = []
    cancel_calls: list[dict] = []

    async def hold(route):
        held.append(route)  # answered only after Cancel is clicked

    async def cancel_route(route):
        cancel_calls.append(json.loads(route.request.post_data))
        await route.fulfill(json={"state": "failed", "message": "Sign-in cancelled."})

    try:
        await open_wizard_signin(page, base_url)
        await page.route("**/api/auth/google/start", hold)
        await page.route("**/api/auth/google/cancel", cancel_route)

        await page.get_by_role("button", name="Connect Google Find Hub").click()
        await page.locator("#fp-setup-google-cancel").wait_for(state="visible", timeout=15000)
        await page.click("#fp-setup-google-cancel")

        assert await page.get_by_role("button", name="Connect Google Find Hub").is_enabled()

        for route in held:
            await route.fulfill(status=202, json={"job_id": "job-late"})

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not cancel_calls:
            await asyncio.sleep(0.01)
        assert cancel_calls == [{"job_id": "job-late"}]
    finally:
        await restore_onboarding(page, base_url)

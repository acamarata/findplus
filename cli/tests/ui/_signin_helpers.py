"""Shared helpers for the sign-in state tests (E14 UI polish).

Purpose    : Open the wizard's sign-in step or Settings > Sign-in with the
             auth routes stubbed by page.route, so every state the shared
             sign-in component (web/app/signin/*) can show is driven
             deterministically, with no Chrome launch and no provider contact.
Inputs     : A Playwright page and the live_server base URL.
Outputs    : Route stubs, a status body builder, and two openers.
Constraints: The wizard opener restores onboarding.* in the caller's finally
             via restore_onboarding(); the session-scoped server is shared.
"""

from __future__ import annotations

import json

from .conftest import SEEDED_COMPLETED_AT


def status_body(*, google=False, apple=False, needs_g=(), needs_a=()) -> dict:
    """A GET /api/auth/status body shaped like providers/auth_status.py's."""
    return {
        "providers": [
            {
                "id": "google-find-hub",
                "signed_in": google,
                "account": "g@example.com" if google else None,
                "attention": "none",
                "needs": list(needs_g),
            },
            {
                "id": "apple-find-my",
                "signed_in": apple,
                "account": "a@example.com" if apple else None,
                "needs": list(needs_a),
            },
        ]
    }


def reply(body, status=200, calls: list | None = None):
    """A route handler answering `body` as JSON, recording each hit in `calls`."""

    async def handler(route):
        if calls is not None:
            calls.append(route.request.url)
        await route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    return handler


async def abort(route):
    """The daemon is unreachable: the request fails at the network layer."""
    await route.abort()


async def _post_setting(page, base_url, key, value):
    await page.request.post(
        f"{base_url}/api/settings/{key}",
        data=json.dumps({"value": value}),
        headers={"Content-Type": "application/json"},
    )


async def reveal_other_ways(page) -> None:
    """Open the Google card's "More ways to sign in" <details> so the paste
    controls are interactable in tests that target them.

    1.2 hides the 1.1 "Find+ opens its own Chrome window" button (spec Q4: hide
    in 1.2, remove in 1.3) but keeps its code; the older state tests unhide it
    here so that code stays covered until it is removed.
    """
    await page.evaluate(
        "() => document.querySelectorAll('details.fp-signin-other').forEach((d) => {"
        " d.open = true;"
        " d.querySelectorAll('[id$=\"-google-signin\"]').forEach((b) => { b.hidden = false; });"
        "})"
    )


async def open_wizard_signin(page, base_url, status: dict | None = None) -> None:
    """Land on the wizard's sign-in step with GET /api/auth/status stubbed."""
    await page.route("**/api/auth/status", reply(status or status_body()))
    await _post_setting(page, base_url, "onboarding.completed_at", None)
    await _post_setting(page, base_url, "onboarding.last_step", "signin")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector("#fp-setup-google-status:not(:empty)", timeout=15000)
    await reveal_other_ways(page)


async def restore_onboarding(page, base_url) -> None:
    await _post_setting(page, base_url, "onboarding.completed_at", SEEDED_COMPLETED_AT)
    await _post_setting(page, base_url, "onboarding.last_step", None)


async def open_settings_signin(page, base_url, status: dict | None = None) -> None:
    """Open Settings with GET /api/auth/status stubbed, and wait for it to render."""
    await page.route("**/api/auth/status", reply(status or status_body()))
    await page.goto(base_url + "/#dashboard")
    await page.click("#btn-settings")
    await page.wait_for_selector("#fp-auth-google-status:not(:empty)", timeout=15000)
    await reveal_other_ways(page)


async def wait_text(page, selector: str, text: str, timeout: int = 15000) -> None:
    """Wait until `selector` is visible and its text contains `text`."""
    await page.locator(selector, has_text=text).wait_for(state="visible", timeout=timeout)

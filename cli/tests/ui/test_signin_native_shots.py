"""Screenshots of the 1.2 sign-in cards for review (opt-in, never in CI).

Purpose    : Save the wizard step and Settings cards in every state the spec's
             table names, at 375/768/1280 and in light and dark, so a person can
             review them. Runs only when FP_SIGNIN_SHOTS names an output folder.
Constraints: Same stub bridge and fake daemon as the state tests; writes PNGs
             only to the folder named; restores onboarding settings.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ._native_stub import ACCOUNT, auth_status, emit
from ._signin_helpers import reply, restore_onboarding, wait_text
from .conftest import set_theme
from .test_signin_native_wizard import _wizard

OUT = os.environ.get("FP_SIGNIN_SHOTS")
pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(not OUT, reason="set FP_SIGNIN_SHOTS=<folder> to save screenshots"),
]
G = "#fp-setup-google"


async def _shot(page, name: str) -> None:
    Path(OUT).mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(Path(OUT) / f"{name}.png"), full_page=True)


@pytest.mark.parametrize("width", (375, 768, 1280))
@pytest.mark.parametrize("theme", ("light", "dark"))
async def test_wizard_states(page, base_url, width, theme):
    try:
        fake = await _wizard(page, base_url, width)
        await set_theme(page, theme)
        tag = f"wizard-{width}-{theme}"
        await _shot(page, f"{tag}-1-not-connected")
        await page.click(f"{G}-native-connect")
        await wait_text(page, f"{G}-native-text", "A Find+ sign-in window opened")
        await _shot(page, f"{tag}-2-waiting")
        fake.set_phase("needs_unlock")
        await wait_text(page, f"{G}-native-text", "One more step")
        await _shot(page, f"{tag}-3-needs-unlock")
        fake.status = auth_status(google=True)
        fake.set_phase("success", account=ACCOUNT, unlocked=True)
        await wait_text(page, f"{G}-status", f"Connected as {ACCOUNT}")
        await _shot(page, f"{tag}-4-success")
    finally:
        await restore_onboarding(page, base_url)


@pytest.mark.parametrize("theme", ("light", "dark"))
async def test_problem_states_and_sheet(page, base_url, theme):
    try:
        fake = await _wizard(page, base_url, 1280)
        await set_theme(page, theme)
        await page.click(f"{G}-native-connect")
        await wait_text(page, f"{G}-native-text", "A Find+ sign-in window opened")
        fake.set_phase(
            "blocked_embedded",
            fallback="use_helper",
            message=(
                "Google would not let Find+ sign you in inside the app. Use your Chrome instead."
            ),
        )
        await wait_text(page, f"{G}-native-text", "Google would not let")
        await _shot(page, f"wizard-1280-{theme}-5-blocked")
        await page.click(f"{G}-native-window-again")
        await emit(
            page,
            "signin-result",
            {
                "provider": "google",
                "mode": "signin",
                "outcome": "error",
                "message": (
                    "The sign-in page did not load. Check your internet connection and try again."
                ),
            },
        )
        await wait_text(page, f"{G}-native-text", "did not load")
        await _shot(page, f"wizard-1280-{theme}-6-error")
        await page.route("**/api/auth/apple/start", reply({"job_id": "a"}, 202))
        await page.route(
            "**/api/auth/apple/status*",
            reply(
                {
                    "job_id": "a",
                    "phase": "needs_code",
                    "message": "",
                    "second_factor": {
                        "kind": "trusted_device",
                        "phone": None,
                        "can_text": True,
                        "sms_options": [{"id": 1, "phone": "+1 (•••) •••-••12"}],
                    },
                }
            ),
        )
        await page.click("#fp-setup-apple-signin")
        await _shot(page, f"wizard-1280-{theme}-7-apple-sheet")
        await page.fill("#fp-setup-apple-id", "sam@example.invalid")
        await page.fill("#fp-setup-apple-password", "x")
        await page.click("#fp-setup-apple-sheet-submit")
        await page.locator("#fp-setup-apple-2fa").wait_for(state="visible")
        await _shot(page, f"wizard-1280-{theme}-8-apple-code")
    finally:
        await restore_onboarding(page, base_url)

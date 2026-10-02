"""The wizard's "Connect your accounts" step in the desktop app, and its a11y.

Purpose    : Both cards side by side (stacked under 768 px), each with one
             Connect; Next waits for one connected account (Skip never waits);
             Google and Apple in either order; the whole step works from the
             keyboard; axe finds nothing serious in any card state or with the
             Apple sheet open, in both themes; the spinner stops under reduced
             motion; no "cookie" or "token" on the main path; a lock purges
             every account and typed value.
Constraints: Stub bridge + fake daemon (_native_stub.py); onboarding settings
             are restored in a finally, the server is shared.
"""

from __future__ import annotations

import pytest
from axe_playwright_python.async_playwright import Axe

from ._native_stub import (
    ACCOUNT,
    APPLE_ACCOUNT,
    FakeNativeDaemon,
    auth_status,
    emit,
    install_bridge,
)
from ._signin_helpers import _post_setting, reply, restore_onboarding, wait_text
from .conftest import set_theme
from .test_a11y import AXE_OPTIONS, BLOCKING, _describe

pytestmark = pytest.mark.asyncio(loop_scope="session")

G = "#fp-setup-google"
A = "#fp-setup-apple"
NEXT = "#fp-wizard-next"


async def _wizard(page, base_url, width=1280) -> FakeNativeDaemon:
    await page.set_viewport_size({"width": width, "height": 900})
    await install_bridge(page)
    fake = FakeNativeDaemon(page)
    await fake.install()
    await _post_setting(page, base_url, "onboarding.completed_at", None)
    await _post_setting(page, base_url, "onboarding.last_step", "signin")
    await page.goto(base_url + "/#/setup")
    await page.wait_for_selector(f"{G}-status:not(:empty)", timeout=15000)
    return fake


async def _google_success(page, fake, *, apple=False) -> None:
    await page.click(f"{G}-native-connect")
    await wait_text(page, f"{G}-native-text", "A Find+ sign-in window opened")
    fake.status = auth_status(google=True, apple=apple)
    fake.set_phase("success", account=ACCOUNT, unlocked=True)
    await emit(
        page,
        "signin-result",
        {
            "provider": "google",
            "mode": "signin",
            "outcome": "success",
            "unlocked": True,
            "account": ACCOUNT,
        },
    )
    await wait_text(page, f"{G}-status", f"Connected as {ACCOUNT}")


async def _apple_success(page, fake, *, google=False) -> None:
    async def code_route(route):
        fake.status = auth_status(google=google, apple=True)
        await route.fulfill(json={"state": "done"})

    await page.route("**/api/auth/apple/start", reply({"job_id": "apple-1"}, 202))
    await page.route(
        "**/api/auth/apple/status*",
        reply(
            {
                "job_id": "apple-1",
                "phase": "needs_code",
                "message": "",
                "second_factor": {
                    "kind": "trusted_device",
                    "phone": None,
                    "can_text": False,
                    "sms_options": [],
                },
            }
        ),
    )
    await page.route("**/api/auth/apple/code", code_route)
    await page.click(f"{A}-signin")
    await page.fill(f"{A}-id", APPLE_ACCOUNT)
    await page.fill(f"{A}-password", "not-a-real-password")
    await page.click(f"{A}-sheet-submit")
    await page.fill(f"{A}-code", "123456")
    await page.click(f"{A}-code-submit")
    await wait_text(page, f"{A}-status", f"Connected as {APPLE_ACCOUNT}")


@pytest.mark.parametrize("width,side_by_side", [(1280, True), (768, True), (375, False)])
async def test_two_cards_side_by_side_then_stacked(page, base_url, width, side_by_side):
    try:
        await _wizard(page, base_url, width)
        assert await page.locator("#setup-view h2").first.inner_text() == "Connect your accounts"
        g = await page.locator(f"{G}-card").bounding_box()
        a = await page.locator(f"{A}-card").bounding_box()
        assert (abs(g["y"] - a["y"]) < 2) is side_by_side, (g, a)
        overflow = await page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1
    finally:
        await restore_onboarding(page, base_url)


async def test_next_waits_for_one_account_and_both_connect_in_any_order(page, base_url):
    try:
        fake = await _wizard(page, base_url)
        assert await page.locator(NEXT).is_disabled()
        assert await page.locator("#fp-setup-signin-next-hint").is_visible()
        assert await page.locator("#fp-wizard-skip").is_enabled()
        await _apple_success(page, fake)
        await page.wait_for_function("(s) => !document.querySelector(s).disabled", arg=NEXT)
        assert await page.locator("#fp-setup-signin-next-hint").is_hidden()
        await _google_success(page, fake, apple=True)
        await wait_text(page, "#fp-setup-signin-status", ACCOUNT)
        assert APPLE_ACCOUNT in await page.locator("#fp-setup-signin-status").inner_text()
        assert await page.locator(f"{A}-ready").is_visible()
        assert await page.locator(f"{G}-ready").is_visible()
    finally:
        await restore_onboarding(page, base_url)


async def test_the_step_works_from_the_keyboard_alone(page, base_url):
    try:
        fake = await _wizard(page, base_url)
        for _ in range(12):
            await page.keyboard.press("Tab")
            focused = await page.evaluate("() => document.activeElement.id")
            if focused == "fp-setup-google-native-connect":
                break
        await page.keyboard.press("Enter")
        await wait_text(page, f"{G}-native-text", "A Find+ sign-in window opened")
        assert len(fake.begins) == 1
        await page.focus(f"{G}-native-cancel")
        await page.keyboard.press("Enter")
        await wait_text(page, f"{G}-native-text", "Cancelled. Nothing changed.")
        await page.focus(f"{A}-signin")
        await page.keyboard.press("Enter")
        assert await page.evaluate("() => document.activeElement.id") == "fp-setup-apple-id"
        await page.keyboard.type(APPLE_ACCOUNT)
        await page.keyboard.press("Tab")
        assert await page.evaluate("() => document.activeElement.id") == "fp-setup-apple-password"
        await page.keyboard.press("Escape")
        assert await page.evaluate("() => document.activeElement.id") == "fp-setup-apple-signin"
    finally:
        await restore_onboarding(page, base_url)


async def _axe(page, label: str) -> None:
    results = await Axe().run(page, options=AXE_OPTIONS)
    blocking = [v for v in results.response["violations"] if v.get("impact") in BLOCKING]
    assert not blocking, "\n".join(_describe(v, label, "", 1280) for v in blocking)


@pytest.mark.parametrize("theme", ("dark", "light"))
async def test_axe_finds_nothing_serious_in_any_state(page, base_url, theme):
    try:
        fake = await _wizard(page, base_url)
        await set_theme(page, theme)
        await _axe(page, f"idle-{theme}")
        await page.click(f"{G}-native-connect")
        await wait_text(page, f"{G}-native-text", "A Find+ sign-in window opened")
        await _axe(page, f"waiting-{theme}")
        fake.set_phase(
            "blocked_embedded",
            fallback="use_helper",
            message="Google would not let Find+ sign you in inside the app.",
        )
        await wait_text(page, f"{G}-native-text", "Google would not let")
        await _axe(page, f"blocked-{theme}")
        await page.click(f"{A}-signin")
        await _axe(page, f"sheet-{theme}")
    finally:
        await restore_onboarding(page, base_url)


async def test_reduced_motion_stops_the_spinner_and_no_jargon_on_the_main_path(page, base_url):
    try:
        await page.emulate_media(reduced_motion="reduce")
        await _wizard(page, base_url)
        await page.click(f"{G}-native-connect")
        await wait_text(page, f"{G}-native-text", "A Find+ sign-in window opened")
        name = await page.locator(f"{G}-native-status .fp-signin-spinner").evaluate(
            "(n) => getComputedStyle(n).animationName"
        )
        assert name == "none"
        main = await page.evaluate("""() => {
          const card = document.getElementById('fp-setup-google-card').cloneNode(true);
          card.querySelectorAll('details, [hidden]').forEach((n) => n.remove());
          return card.textContent.toLowerCase();
        }""")
        assert "cookie" not in main and "token" not in main
    finally:
        await restore_onboarding(page, base_url)


async def test_a_lock_purges_accounts_and_typed_values(page, base_url):
    try:
        fake = await _wizard(page, base_url)
        await _google_success(page, fake)
        await page.click(f"{A}-signin")
        await page.fill(f"{A}-id", APPLE_ACCOUNT)
        await page.evaluate("() => import('/static/app/lock.js').then((m) => m.showLock())")
        await page.locator("#lock-screen").wait_for(state="visible")
        html = await page.content()
        assert ACCOUNT not in html and APPLE_ACCOUNT not in html
    finally:
        await page.goto(base_url + "/#dashboard")
        await restore_onboarding(page, base_url)

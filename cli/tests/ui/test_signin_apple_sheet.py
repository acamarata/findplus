"""Apple in one sheet: Connect, Apple ID and password, the code, Connected.

Purpose    : The Apple card's single Connect opens a <dialog> sheet (focus on the
             Apple ID, Escape cancels without closing Settings). The code step's
             wording follows GET /api/auth/apple/status (trusted device or the
             masked number), "Use a text message instead" posts
             /api/auth/apple/text, a code must be 6 digits before it is sent,
             Cancel and Start over post /api/auth/apple/cancel, and success
             closes the sheet, shows "Connected as ..." with a chip and moves
             focus there. The password never stays in the DOM.
Constraints: Every Apple route is answered by page.route: no Apple account, no
             network.
"""

from __future__ import annotations

import json

import pytest

from ._native_stub import APPLE_ACCOUNT, auth_status
from ._signin_helpers import reply, wait_text

pytestmark = pytest.mark.asyncio(loop_scope="session")

P = "#fp-auth-apple"
SHEET = f"{P}-sheet"
PHONE = "+1 (•••) •••-••12"


def _needs_code(kind="trusted_device", can_text=True, phone=None) -> dict:
    return {
        "job_id": "apple-1",
        "phase": "needs_code",
        "message": "",
        "account": None,
        "second_factor": {
            "kind": kind,
            "phone": phone,
            "can_text": can_text,
            "sms_options": [{"id": 7, "phone": PHONE}],
        },
        "attempts_left": 5,
        "available": True,
        "install_hint": None,
    }


async def _open(page, base_url) -> dict:
    """Settings with a mutable /api/auth/status; returns the dict to mutate."""
    holder = {"status": auth_status()}

    async def status_route(route):
        await route.fulfill(json=holder["status"])

    await page.add_init_script("window.__FP_TEST_POLL_MS__ = 50;")
    await page.route("**/api/auth/status", status_route)
    await page.goto(base_url + "/#dashboard")
    await page.click("#btn-settings")
    await page.wait_for_selector(f"{P}-status:not(:empty)", timeout=15000)
    return holder


async def _to_code(page, status: dict, posted: list | None = None) -> None:
    async def start(route):
        if posted is not None:
            posted.append(json.loads(route.request.post_data))
        await route.fulfill(status=202, json={"job_id": "apple-1"})

    await page.route("**/api/auth/apple/start", start)
    await page.route("**/api/auth/apple/status*", reply(status))
    await page.click(f"{P}-signin")
    await page.fill(f"{P}-id", APPLE_ACCOUNT)
    await page.fill(f"{P}-password", "not-a-real-password")
    await page.click(f"{P}-sheet-submit")
    await page.locator(f"{P}-2fa").wait_for(state="visible", timeout=15000)


async def test_connect_opens_the_sheet_and_escape_only_closes_the_sheet(page, base_url):
    await _open(page, base_url)
    assert await page.locator(f"{P}-signin").inner_text() == "Connect"
    await page.click(f"{P}-signin")
    assert await page.locator(SHEET).evaluate("(d) => d.open && d.matches(':modal')")
    assert await page.evaluate("() => document.activeElement.id") == "fp-auth-apple-id"
    await page.keyboard.press("Escape")
    assert not await page.locator(SHEET).evaluate("(d) => d.open")
    assert await page.locator("#settings-modal").is_visible()  # Settings stayed open
    assert await page.evaluate("() => document.activeElement.id") == "fp-auth-apple-signin"


async def test_trusted_device_code_then_connected_with_focus(page, base_url):
    holder = await _open(page, base_url)
    posted: list[dict] = []
    sent: list[dict] = []
    await _to_code(page, _needs_code(), posted)
    assert posted == [{"apple_id": APPLE_ACCOUNT, "password": "not-a-real-password"}]
    assert await page.locator(f"{P}-password").input_value() == ""
    prompt = await page.locator(f"{P}-code-prompt").inner_text()
    assert prompt == "Enter the 6-digit code shown on your iPhone, iPad or Mac."
    assert await page.locator(f"{P}-text").is_visible()

    async def code_route(route):
        sent.append(json.loads(route.request.post_data))
        holder["status"] = auth_status(apple=True)
        await route.fulfill(json={"state": "done"})

    await page.route("**/api/auth/apple/code", code_route)
    await page.fill(f"{P}-code", "12ab")
    await page.click(f"{P}-code-submit")
    await wait_text(page, f"{P}-error", "6 digits")
    assert sent == []
    await page.fill(f"{P}-code", "123 456")
    await page.press(f"{P}-code", "Enter")
    await wait_text(page, f"{P}-status", f"Connected as {APPLE_ACCOUNT}")
    assert sent == [{"job_id": "apple-1", "code": "123456"}]
    assert not await page.locator(SHEET).evaluate("(d) => d.open")
    assert await page.locator(f"{P}-ready").is_visible()
    await page.wait_for_function(
        "() => document.activeElement && document.activeElement.id === 'fp-auth-apple-status'"
    )
    html = await page.content()
    assert "not-a-real-password" not in html


async def test_use_a_text_message_instead(page, base_url):
    await _open(page, base_url)
    texted: list[dict] = []

    async def text_route(route):
        texted.append(json.loads(route.request.post_data))
        await route.fulfill(json={"phase": "needs_code", "message": "x", "phone": PHONE})

    await page.route("**/api/auth/apple/text", text_route)
    await _to_code(page, _needs_code())
    await page.click(f"{P}-text")
    await wait_text(page, f"{P}-code-prompt", f"by text message to {PHONE}")
    assert texted == [{"job_id": "apple-1"}]
    assert await page.locator(f"{P}-text").is_hidden()
    assert await page.evaluate("() => document.activeElement.id") == "fp-auth-apple-code"


async def test_an_sms_code_names_the_number_and_offers_no_text_button(page, base_url):
    await _open(page, base_url)
    await _to_code(page, _needs_code(kind="sms", phone=PHONE))
    assert PHONE in await page.locator(f"{P}-code-prompt").inner_text()
    assert await page.locator(f"{P}-text").is_hidden()


async def test_cancel_posts_cancel_and_says_nothing_changed(page, base_url):
    await _open(page, base_url)
    cancelled: list[dict] = []

    async def cancel_route(route):
        cancelled.append(json.loads(route.request.post_data))
        await route.fulfill(json={"phase": "cancelled", "message": "Cancelled. Nothing changed."})

    await page.route("**/api/auth/apple/cancel", cancel_route)
    await _to_code(page, _needs_code())
    await page.click(f"{P}-sheet-cancel")
    await wait_text(page, f"{P}-note", "Cancelled. Nothing changed.")
    assert not await page.locator(SHEET).evaluate("(d) => d.open")
    await page.wait_for_timeout(200)
    assert cancelled == [{"job_id": "apple-1"}]


async def test_start_over_goes_back_to_the_apple_id_and_drops_the_job(page, base_url):
    await _open(page, base_url)
    cancelled: list[str] = []
    await page.route("**/api/auth/apple/cancel", reply({"phase": "cancelled"}, 200, cancelled))
    await _to_code(page, _needs_code())
    await page.click(f"{P}-code-restart")
    assert await page.locator(f"{P}-form").is_visible()
    assert await page.locator(f"{P}-2fa").is_hidden()
    await page.wait_for_timeout(200)
    assert len(cancelled) == 1


async def test_the_first_run_download_is_named_while_it_runs(page, base_url):
    await _open(page, base_url)
    await page.route("**/api/auth/apple/start", reply({"job_id": "apple-2"}, 202))
    await page.route(
        "**/api/auth/apple/status*",
        reply({"job_id": "apple-2", "phase": "preparing", "message": "", "second_factor": None}),
    )
    await page.click(f"{P}-signin")
    await page.fill(f"{P}-id", APPLE_ACCOUNT)
    await page.fill(f"{P}-password", "x")
    await page.click(f"{P}-sheet-submit")
    await wait_text(page, f"{P}-progress", "Preparing Apple sign-in (one-time download")


async def test_lost_apple_sign_in_has_one_button_into_the_sheet(page, base_url):
    holder = await _open(page, base_url)
    holder["status"] = auth_status(apple=True, att_a="reauth")
    await page.click("#btn-close-settings")
    await page.click("#btn-settings")
    await page.locator(f"{P}-revoked").wait_for(state="visible", timeout=15000)
    assert await page.locator(f"{P}-signin").is_hidden()
    await page.click(f"{P}-revoked-btn")
    assert await page.locator(SHEET).evaluate("(d) => d.open")
    assert await page.locator(f"{P}-id").input_value() == APPLE_ACCOUNT

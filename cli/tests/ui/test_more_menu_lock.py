"""The phone More menu's Lock item follows the desktop topbar's own Lock
button (UAT4 N30).

Purpose    : lock.js's refreshLockState() hides #btn-lock (the desktop
             topbar's own control) with no PIN configured. The relayed
             More-menu item (tabbar.js, data-relays-to="btn-lock") had no
             matching condition, so a phone user with no PIN saw "Lock" in
             the menu, and tapping it opened a lock screen any PIN dismissed.
Inputs     : live_server (conftest.py). The first test runs against the
             default seeded state (no PIN configured); the second mocks
             /api/lock/status rather than setting a real PIN, since this
             module shares its server with every other `ui/` file and a real
             PIN would lock the app for whichever module runs next.
Outputs    : none (assertions only).
Constraints: Split out of test_responsive.py (PRI rule 7, <=300 lines/file):
             that file was already at its cap.
"""

from __future__ import annotations

import json

import pytest
from playwright.async_api import expect

pytestmark = pytest.mark.asyncio(loop_scope="session")

PHONE_WIDTH = 375
PHONE_HEIGHT = 812
PIN = "864213"


async def _open_more_menu(page, base_url):
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")
    await page.click("#btn-more")
    await page.wait_for_selector("#fp-more-menu:not(.hidden)")


async def test_lock_item_hidden_in_more_menu_when_no_pin_configured(page, base_url):
    """The default seeded server has no PIN, so #btn-lock is hidden; the
    relayed menu item must be hidden right along with it.

    UAT5 N30: `#fp-more-menu button`'s own `display: flex` rule
    (web/responsive.css) beat `.hidden`'s `display: none` at equal
    specificity, so the item still painted even with the class applied.
    `to_be_hidden()` checks actual computed visibility, not just the class,
    so it catches that regression where the class-only assertion below did
    not."""
    await _open_more_menu(page, base_url)
    await expect(page.locator("#btn-lock")).to_be_hidden()

    lock_item = page.locator('[data-relays-to="btn-lock"]')
    await expect(lock_item).to_be_hidden()
    assert "hidden" in (await lock_item.get_attribute("class") or "")


async def test_lock_item_hidden_in_more_menu_after_pin_removed(page, base_url):
    """A PIN configured then removed must leave the relayed item hidden
    again, not just on a server that never had one (UAT5 N30 fresh-load vs.
    removal split)."""
    set_resp = await page.request.post(
        base_url + "/api/settings/pin",
        data=json.dumps({"new_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert set_resp.ok, await set_resp.text()
    try:
        del_resp = await page.request.delete(
            f"{base_url}/api/settings/pin",
            data=json.dumps({"current_pin": PIN}),
            headers={"Content-Type": "application/json"},
        )
        assert del_resp.ok, await del_resp.text()

        await _open_more_menu(page, base_url)
        await expect(page.locator("#btn-lock")).to_be_hidden()
        lock_item = page.locator('[data-relays-to="btn-lock"]')
        await expect(lock_item).to_be_hidden()
    finally:
        # Belt and braces: if the DELETE above ever fails, leave the shared
        # session-scoped server unlocked for whichever module runs next.
        status_resp = await page.request.get(base_url + "/api/lock/status")
        if (await status_resp.json()).get("lock_configured"):
            await page.request.delete(
                f"{base_url}/api/settings/pin",
                data=json.dumps({"current_pin": PIN}),
                headers={"Content-Type": "application/json"},
            )


async def test_lock_item_shown_in_more_menu_when_pin_configured(page, base_url):
    """The mirror in the other direction: a PIN-configured, lock-enabled
    account must still be able to lock from the phone More menu.

    /api/lock/status is mocked rather than setting a real PIN through the
    API, since this session-scoped server is shared with every other `ui/`
    module and a real PIN would lock the app for whichever runs next.
    """

    async def fulfill(route):
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"locked": False, "lock_configured": True, "lock_enabled": True, "idle_minutes": 0}
            ),
        )

    await page.route("**/api/lock/status", fulfill)
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")
    await page.wait_for_function(
        "() => !document.getElementById('btn-lock').classList.contains('hidden')",
        timeout=15000,
    )

    await page.click("#btn-more")
    await page.wait_for_selector("#fp-more-menu:not(.hidden)")
    lock_item = page.locator('[data-relays-to="btn-lock"]')
    await expect(lock_item).to_be_visible()
    assert "hidden" not in (await lock_item.get_attribute("class") or "")

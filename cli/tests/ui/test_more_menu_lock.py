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

pytestmark = pytest.mark.asyncio(loop_scope="session")

PHONE_WIDTH = 375
PHONE_HEIGHT = 812


async def _open_more_menu(page, base_url):
    await page.set_viewport_size({"width": PHONE_WIDTH, "height": PHONE_HEIGHT})
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell:not(.hidden)")
    await page.click("#btn-more")
    await page.wait_for_selector("#fp-more-menu:not(.hidden)")


async def test_lock_item_hidden_in_more_menu_when_no_pin_configured(page, base_url):
    """The default seeded server has no PIN, so #btn-lock is hidden; the
    relayed menu item must be hidden right along with it."""
    await _open_more_menu(page, base_url)
    assert "hidden" in (await page.get_attribute("#btn-lock", "class") or "")

    lock_item = page.locator('[data-relays-to="btn-lock"]')
    assert "hidden" in (await lock_item.get_attribute("class") or "")


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
    assert "hidden" not in (await lock_item.get_attribute("class") or "")

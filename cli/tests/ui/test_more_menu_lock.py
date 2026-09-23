"""The phone More menu's Lock item follows the desktop topbar's own Lock
button (UAT4 N30).

Purpose    : lock.js's refreshLockState() hides #btn-lock (the desktop
             topbar's own control) with no PIN configured. The relayed
             More-menu item (tabbar.js, data-relays-to="btn-lock") had no
             matching condition, so a phone user with no PIN saw "Lock" in
             the menu, and tapping it opened a lock screen any PIN dismissed.
Inputs     : live_server (conftest.py). The first test runs against the
             default seeded state (no PIN configured); the other two set a
             real PIN through the API (a mocked /api/lock/status alone left
             the item's hidden class racing against the unmocked
             /api/settings loadSettings() also reads on every load -- see
             CI run 35904027243 in the third test's docstring) and remove it
             again in a `finally`, since this module shares its server with
             every other `ui/` file and a real PIN would lock the app for
             whichever module runs next.
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
    so it catches that regression where a class-only assertion would not.
    #btn-lock itself is checked by class, not visibility: responsive.css
    collapses every topbar-actions button but #btn-more behind the phone
    tier's More menu regardless of state, so `to_be_visible()` on #btn-lock
    at this viewport is never true and would not be testing anything."""
    await _open_more_menu(page, base_url)
    await expect(page.locator("#btn-lock")).to_contain_class("hidden")

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
        await expect(page.locator("#btn-lock")).to_contain_class("hidden")
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

    A real PIN is set through the API (like the other tests here), not
    mocked via page.route: mocking only /api/lock/status left
    #btn-lock's hidden class fed by two disagreeing sources --
    lock.js's refreshLockState() (mocked, says visible) and
    settings.js's loadSettings(), which bootDashboard() also awaits on
    every load and which reads the real, unmocked /api/settings (no PIN
    ever set for this session-scoped server, so it says hidden). Whichever
    of the two awaits lands last on a given run decided the final class,
    which is what made CI run 35904027243 flake: loadSettings() sometimes
    won the race and re-hid the item after refreshLockState() had already
    shown it. A real PIN makes both endpoints agree, so there is nothing
    left to race.

    #btn-lock is checked by class, not visibility, for the same reason as
    the other two tests here: responsive.css hides every topbar-actions
    button but #btn-more at this viewport regardless of lock state.
    """
    set_resp = await page.request.post(
        base_url + "/api/settings/pin",
        data=json.dumps({"new_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert set_resp.ok, await set_resp.text()
    try:
        await _open_more_menu(page, base_url)
        await expect(page.locator("#btn-lock")).not_to_contain_class("hidden")
        lock_item = page.locator('[data-relays-to="btn-lock"]')
        await expect(lock_item).to_be_visible()
        assert "hidden" not in (await lock_item.get_attribute("class") or "")
    finally:
        # Leave the shared session-scoped server unlocked for whichever
        # module runs next.
        del_resp = await page.request.delete(
            f"{base_url}/api/settings/pin",
            data=json.dumps({"current_pin": PIN}),
            headers={"Content-Type": "application/json"},
        )
        assert del_resp.ok, await del_resp.text()

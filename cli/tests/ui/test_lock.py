"""Playwright browser tests for the app lock and its honesty notice
(P1-E10-W6-S1-T4/T5).

`live_server` is session-scoped and shared with test_groups.py/test_places.py
(alphabetically before and after this file), so the one test here that
engages the lock removes the PIN again before returning — leaving the
shared server unlocked for whichever module runs next.

The DOM/dialog purge tests split out to test_lock_purge.py (PRI rule 7,
<=300 lines/file); that module imports PIN from here.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

PIN = "864213"


async def test_lock_status_endpoint(page, base_url):
    resp = await page.request.get(base_url + "/api/lock/status")
    assert resp.ok
    assert (await resp.json())["locked"] is False


async def test_dashboard_accessible_unlocked(page, base_url):
    resp = await page.request.get(base_url + "/")
    assert resp.status == 200
    assert "<html" in (await resp.text()).lower()


async def test_lock_not_encryption_notice_present(page, base_url):
    await page.goto(base_url + "/")
    await page.click("#btn-settings")
    notice = page.locator("#fp-notice-lock")
    await notice.wait_for(state="visible")
    assert "The app lock stops casual browsing." in await notice.inner_text()


async def test_places_repopulate_after_unlock_without_reload(page, base_url):
    """build-notes.md § E10-S2 bug 1: a session that boots locked never got its
    Places tab back after unlock — places.js's one-time loader ran (and 401'd)
    before the lock check resolved, and nothing re-triggered it post-unlock.
    Fixed by hideLockAndRestore() reloading places/groups/alerts/notices
    (§ E10-S2 fix loop); this asserts it without the page.reload() workaround
    screenshots.py used. Also covers notices.js: a locked boot's /api/config
    401 left the six honesty paragraphs blank all session (PROMPT.md §2
    invariant 4 requires the text actually render, not just be fetchable).
    """
    set_resp = await page.request.post(
        base_url + "/api/settings/pin",
        data=json.dumps({"new_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert set_resp.ok, await set_resp.text()
    lock_resp = await page.request.post(base_url + "/api/lock/lock")
    assert lock_resp.ok

    try:
        await page.goto(base_url + "/")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        assert await page.locator("#map svg path.leaflet-interactive").count() == 0

        await page.fill("#lock-pin", PIN)
        await page.click("#lock-submit")
        # "#lock-screen.hidden" would never resolve: wait_for_selector defaults
        # to state="visible", and .hidden means display:none — wait for the
        # element to go hidden, or for #app-shell to come back instead.
        await page.locator("#app-shell:not(.hidden)").wait_for(state="visible")

        await page.click('button[data-tab="places"]')
        await page.wait_for_selector("#map svg path.leaflet-interactive")

        await page.click("#btn-settings")
        notice = page.locator("#fp-notice-lock")
        await notice.wait_for(state="visible")
        assert "The app lock stops casual browsing." in await notice.inner_text()
    finally:
        del_resp = await page.request.delete(
            f"{base_url}/api/settings/pin",
            data=json.dumps({"current_pin": PIN}),
            headers={"Content-Type": "application/json"},
        )
        assert del_resp.ok, await del_resp.text()


async def test_lock_redirects_api_when_locked(page, base_url):
    set_resp = await page.request.post(
        base_url + "/api/settings/pin",
        data=json.dumps({"new_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert set_resp.ok, await set_resp.text()

    lock_resp = await page.request.post(base_url + "/api/lock/lock")
    assert lock_resp.ok

    devices_resp = await page.request.get(base_url + "/api/devices")
    assert devices_resp.status == 401

    try:
        unlock_resp = await page.request.post(
            base_url + "/api/lock/unlock",
            data=json.dumps({"pin": PIN}),
            headers={"Content-Type": "application/json"},
        )
        assert unlock_resp.ok, await unlock_resp.text()
    finally:
        # Restores the shared live_server to "no PIN" for test_places.py,
        # which runs after this file alphabetically. current_pin travels in
        # the JSON body (carry-forward #1 fixed concurrently by another
        # epic mid-build — web/app/settings.js already sends it this way).
        del_resp = await page.request.delete(
            f"{base_url}/api/settings/pin",
            data=json.dumps({"current_pin": PIN}),
            headers={"Content-Type": "application/json"},
        )
        assert del_resp.ok, await del_resp.text()


async def test_the_lock_screen_states_the_lock_is_not_encryption(page, base_url):
    """honesty round 2 F12: the caveat was only in Settings, which sits behind the lock.

    /api/lock/requirements is public precisely so this screen can render it.
    The one surface presenting the lock as protection said only "Find+ is
    locked / Enter your PIN to continue."
    """
    from findplus import honesty

    await page.goto(base_url + "/")
    await page.wait_for_selector("#map")
    set_resp = await page.request.post(
        base_url + "/api/settings/pin",
        data=json.dumps({"new_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert set_resp.ok, await set_resp.text()
    try:
        shown = await page.evaluate(
            """async () => {
                const lock = await import('/static/app/lock.js');
                await lock.showLock();
                const el = document.getElementById('lock-caveat-screen');
                for (let i = 0; i < 50 && el.textContent === ''; i++) {
                    await new Promise((r) => setTimeout(r, 100));
                }
                return {
                    visible: !document.getElementById('lock-screen').classList.contains('hidden'),
                    caveat: el.textContent,
                };
            }"""
        )
        assert shown["visible"] is True
        assert shown["caveat"] == honesty.LOCK_NOT_ENCRYPTION
    finally:
        unlock = await page.request.post(
            base_url + "/api/lock/unlock",
            data=json.dumps({"pin": PIN}),
            headers={"Content-Type": "application/json"},
        )
        assert unlock.ok, await unlock.text()
        del_resp = await page.request.delete(
            f"{base_url}/api/settings/pin",
            data=json.dumps({"current_pin": PIN}),
            headers={"Content-Type": "application/json"},
        )
        assert del_resp.ok, await del_resp.text()

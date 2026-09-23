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

import asyncio
import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

PIN = "864213"


async def _wait_for_lock_caveat(page) -> str:
    """The text of #lock-caveat, once it actually has some.

    openSettings() (web/app/settings.js) now unhides #settings-modal
    immediately on click and fills #lock-caveat afterward, from a separate
    /api/lock/requirements round trip -- so `state="visible"` alone no longer
    proves the text has landed (CI run 35546305331 fix; see
    test_settings_opens_before_config_resolves below for the race this
    replaced).
    """
    await page.wait_for_function(
        "() => document.getElementById('lock-caveat').textContent.length > 0"
    )
    return await page.locator("#lock-caveat").inner_text()


async def test_lock_status_endpoint(page, base_url):
    resp = await page.request.get(base_url + "/api/lock/status")
    assert resp.ok
    assert (await resp.json())["locked"] is False


async def test_dashboard_accessible_unlocked(page, base_url):
    resp = await page.request.get(base_url + "/")
    assert resp.status == 200
    assert "<html" in (await resp.text()).lower()


async def test_lock_not_encryption_notice_present(page, base_url):
    """The sentence appears once in the dialog, under App lock.

    It used to render twice in the same scrollable modal -- here and again in
    the Notices list -- so #fp-notice-lock was dropped and #lock-caveat, the
    copy next to the setting it describes, is the one that stays
    (E1 honesty round 3 F13).
    """
    await page.goto(base_url + "/")
    await page.click("#btn-settings")
    assert "The app lock stops casual browsing." in await _wait_for_lock_caveat(page)

    copies = await page.evaluate(
        """() => [...document.querySelectorAll('#settings-modal p')]
            .filter((p) => p.textContent.includes('The app lock stops casual browsing.')).length"""
    )
    assert copies == 1, f"the caveat renders {copies} times in one dialog"


async def _set_pin_and_lock(page, base_url) -> None:
    set_resp = await page.request.post(
        base_url + "/api/settings/pin",
        data=json.dumps({"new_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert set_resp.ok, await set_resp.text()
    lock_resp = await page.request.post(base_url + "/api/lock/lock")
    assert lock_resp.ok


async def _remove_pin(page, base_url) -> None:
    del_resp = await page.request.delete(
        f"{base_url}/api/settings/pin",
        data=json.dumps({"current_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert del_resp.ok, await del_resp.text()


async def test_no_console_errors_on_a_locked_cold_boot(page, base_url):
    """UAT2 N12: notices.js used to self-invoke a GET /api/config at parse
    time, before refreshLockState() had a chance to show the lock screen --
    every locked cold boot logged "loadNotices: /api/config returned 401"
    plus the browser's own failed-request console error. loadNotices() now
    only runs from main.js's boot chain, after the lock check confirms the
    app is not locked.
    """
    await _set_pin_and_lock(page, base_url)
    console_errors: list[str] = []
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )
    try:
        await page.goto(base_url + "/")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        await page.wait_for_timeout(500)  # let any stray boot-time fetches settle
        assert console_errors == [], f"console errors on a locked load: {console_errors}"
    finally:
        unlock_resp = await page.request.post(
            f"{base_url}/api/lock/unlock",
            data=json.dumps({"pin": PIN}),
            headers={"Content-Type": "application/json"},
        )
        assert unlock_resp.ok, await unlock_resp.text()
        await _remove_pin(page, base_url)


async def test_places_repopulate_after_unlock_without_reload(
    page, base_url, reset_alert_and_observation_state
):
    """build-notes.md § E10-S2 bug 1: a session that boots locked never got its
    Places tab back after unlock — places.js's one-time loader ran (and 401'd)
    before the lock check resolved, and nothing re-triggered it post-unlock.
    Fixed by hideLockAndRestore() reloading places/groups/alerts/notices
    (§ E10-S2 fix loop); this asserts it without the page.reload() workaround
    screenshots.py used. Also covers notices.js: a locked boot's /api/config
    401 left the six honesty paragraphs blank all session (PROMPT.md §2
    invariant 4 requires the text actually render, not just be fetchable).

    This is a real cold boot (page.goto() + unlock), so it requests
    reset_alert_and_observation_state to clear alert rules/deliveries earlier
    files in the session-scoped suite left behind before rendering the
    dashboard (E13 loop3 L3-3, same accumulation test_groups_dialog_purge.py's
    locked-boot test hit).
    """
    await _set_pin_and_lock(page, base_url)
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
        assert "The app lock stops casual browsing." in await _wait_for_lock_caveat(page)
    finally:
        await _remove_pin(page, base_url)


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
    await page.wait_for_selector("#map.leaflet-container")
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


async def test_settings_opens_before_config_resolves(page, base_url):
    """CI run 35546305331: openSettings() (web/app/settings.js) used to read
    state.config for the About line before unhiding #settings-modal, so a
    click that landed before bootDashboard()'s /api/config request resolved
    threw and left the whole dialog -- #lock-caveat included -- hidden
    forever. The fix opens the dialog first and fills the About line (which
    needs state.config) once loadConfig() actually lands, reusing the same
    loader main.js does instead of a second fetch. Delaying /api/config here
    reproduces the slow-boot case deterministically instead of racing a real
    cold start.
    """

    async def delay_config(route):
        await asyncio.sleep(1.5)
        await route.continue_()

    await page.route("**/api/config", delay_config)
    await page.goto(base_url + "/")
    await page.click("#btn-settings")

    # Open immediately: well inside the 1.5s /api/config delay above.
    await page.locator("#settings-modal:not(.hidden)").wait_for(state="visible", timeout=500)
    about = page.locator("#settings-about")
    assert await about.inner_text() == ""

    # The About line (state.config.poll_interval_minutes) fills in once the
    # delayed response lands, not before.
    await page.wait_for_function(
        "() => document.getElementById('settings-about').textContent.length > 0",
        timeout=5000,
    )
    assert "polling every" in await about.inner_text()

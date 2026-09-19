"""Playwright browser tests for the app lock and its honesty notice
(P1-E10-W6-S1-T4/T5).

`live_server` is session-scoped and shared with test_groups.py/test_places.py
(alphabetically before and after this file), so the one test here that
engages the lock removes the PIN again before returning — leaving the
shared server unlocked for whichever module runs next.
"""

from __future__ import annotations

import contextlib
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


LEAKED_STRINGS = ("Home Tag", "Away Tag", "Stale Tag", "Family", "Lock purge rule", "41.1")


async def _populate_places_groups_alerts(page, base_url):
    """Render the place circle, group presence panel/legend/select and the
    alerts rules table — everything `purge()` must destroy on lock."""
    await page.click('button[data-tab="places"]')
    await page.wait_for_selector("#map svg path.leaflet-interactive")
    await page.click('button[data-tab="groups"]')
    await page.select_option("#fp-group-select", label="Family")
    await page.wait_for_selector("#fp-presence-panel .fp-verdict")
    await page.click('button[data-tab="alerts"]')
    await page.locator("#fp-rules-tbody tr", has_text="Lock purge rule").wait_for(state="visible")
    html = await page.content()
    for leaked in LEAKED_STRINGS:
        assert leaked in html, f"fixture setup did not render {leaked!r}"


async def _assert_dom_purged(page):
    assert await page.locator("#map svg path.leaflet-interactive").count() == 0
    assert (await page.locator("#fp-presence-panel").inner_text()).strip() == ""
    assert (await page.locator("#fp-group-legend").inner_text()).strip() == ""
    assert await page.locator("#fp-group-select option").count() == 0
    assert await page.locator("#fp-rules-tbody tr").count() == 0
    html = await page.content()
    for leaked in LEAKED_STRINGS:
        assert leaked not in html, f"{leaked!r} survived the lock"


async def _delete_rule_named(page, base_url, name):
    rules_resp = await page.request.get(base_url + "/api/alerts/rules")
    for rule in await rules_resp.json():
        if rule["name"] == name:
            await page.request.delete(f"{base_url}/api/alerts/rules/{rule['id']}")


async def _setup_purge_fixture(page, base_url):
    """Create the rule, set the PIN, and enable the lock so #btn-lock (hidden
    while lock_enabled is off) is clickable — locking through the API alone
    never triggers showLock() client-side; nothing on an already-loaded page
    polls lock status."""
    rule_resp = await page.request.post(
        base_url + "/api/alerts/rules",
        data=json.dumps({"name": "Lock purge rule", "device_id": "TAG-HOME", "channel": "webhook"}),
        headers={"Content-Type": "application/json"},
    )
    assert rule_resp.ok, await rule_resp.text()
    set_resp = await page.request.post(
        base_url + "/api/settings/pin",
        data=json.dumps({"new_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert set_resp.ok, await set_resp.text()
    enable_resp = await page.request.put(
        base_url + "/api/settings",
        data=json.dumps({"lock_enabled": True}),
        headers={"Content-Type": "application/json"},
    )
    assert enable_resp.ok, await enable_resp.text()


async def _teardown_purge_fixture(page, base_url):
    """Best-effort unlock first: a failed assertion in the test can leave the
    shared live_server locked, which would 401 the PIN delete below and
    cascade into every test that runs after this file."""
    with contextlib.suppress(Exception):
        await page.request.post(
            f"{base_url}/api/lock/unlock",
            data=json.dumps({"pin": PIN}),
            headers={"Content-Type": "application/json"},
        )
    del_resp = await page.request.delete(
        f"{base_url}/api/settings/pin",
        data=json.dumps({"current_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert del_resp.ok, await del_resp.text()
    await _delete_rule_named(page, base_url, "Lock purge rule")


async def test_lock_purges_places_groups_and_alerts_from_the_dom(page, base_url):
    """reviewer-E10 finding: locking only added `.hidden` to #app-shell —
    place/group-member circles stayed in `.leaflet-overlay-pane`, the
    presence panel/legend/group-select kept names, and the alerts rules
    table kept place/device names. Fixed by places.js/groups.js/alerts.js
    each exporting `purge()`, called from lock.js's purgeRenderedData().
    """
    await _setup_purge_fixture(page, base_url)
    try:
        await page.goto(base_url + "/")
        await page.locator("#app-shell:not(.hidden)").wait_for(state="visible")
        await _populate_places_groups_alerts(page, base_url)

        # Lock via the real UI control, exercising the exact "user is looking
        # at live data and clicks Lock" path reviewer-E10 measured — an
        # api.js-side 401 or a reload would never have exposed this defect.
        await page.click("#btn-lock")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        await _assert_dom_purged(page)

        # Unlock and confirm everything comes back without a page reload.
        await page.fill("#lock-pin", PIN)
        await page.click("#lock-submit")
        await page.locator("#app-shell:not(.hidden)").wait_for(state="visible")
        await page.click('button[data-tab="places"]')
        await page.wait_for_selector("#map svg path.leaflet-interactive")
        await page.click('button[data-tab="alerts"]')
        row = page.locator("#fp-rules-tbody tr", has_text="Lock purge rule")
        await row.wait_for(state="visible")
    finally:
        await _teardown_purge_fixture(page, base_url)


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

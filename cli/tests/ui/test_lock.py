"""Playwright browser tests for the app lock and its honesty notice
(P1-E10-W6-S1-T4/T5).

`live_server` is session-scoped and shared with test_groups.py/test_places.py
(alphabetically before and after this file), so the one test here that
engages the lock removes the PIN again before returning — leaving the
shared server unlocked for whichever module runs next.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

PIN = "8642"


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

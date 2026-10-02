"""The update corner button and Settings > Updates, with a stubbed desktop bridge.

Purpose    : "Restart to update" shows only inside the app with an update staged
             and asks the shell (Tauri command apply_update) to install; a browser
             tab only links to the release; "Later" hides it; Settings states the
             one request automatic updates make, word for word.
Constraints: /api/update/status is answered by the test (route), so nothing is
             downloaded and no real app is touched. The bridge is plain page script.
"""

from __future__ import annotations

import json

import pytest

from findplus import honesty

pytestmark = pytest.mark.asyncio(loop_scope="session")

BRIDGE = """
window.__fpCalls = [];
window.__findplus_native = true;
window.__TAURI__ = { core: { invoke: async (cmd) => { window.__fpCalls.push(cmd); return "started"; } } };
"""


def _status(**over):
    body = {
        "current_version": "1.2.1",
        "auto": True,
        "can_install": True,
        "checking": False,
        "checked_at": "2026-10-02T12:00:00+00:00",
        "latest_version": "1.3.0",
        "available": True,
        "release_url": "https://github.com/acamarata/findplus/releases/tag/v1.3.0",
        "staged_version": "1.3.0",
        "staged_source": "release",
        "error": None,
        "last_attempt_failed": False,
        "last_result": None,
        "auto_install_ready": True,
        "backup_at": None,
        "installed": None,
    }
    return {**body, **over}


async def _open(page, base_url, body, native=True):
    if native:
        await page.add_init_script(BRIDGE)

    async def answer(route):
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    await page.route("**/api/update/status", answer)
    await page.goto(base_url + "/")
    await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")


async def test_the_app_offers_restart_to_update_and_asks_the_shell(page, base_url):
    await _open(page, base_url, _status())
    banner = page.locator("#fp-update-banner")
    await banner.wait_for()
    assert "Find+ 1.3.0 is ready." in await banner.inner_text()
    await page.click("#fp-update-restart")
    await page.get_by_text("Installing. Find+ restarts in a moment.").wait_for()
    assert await page.evaluate("window.__fpCalls") == ["apply_update"]


async def test_later_hides_it(page, base_url):
    await _open(page, base_url, _status())
    await page.locator("#fp-update-banner").wait_for()
    await page.get_by_role("button", name="Later").click()
    assert await page.locator("#fp-update-banner").count() == 0


async def test_a_browser_tab_only_links_to_the_release(page, base_url):
    await _open(page, base_url, _status(staged_version=None, can_install=False), native=False)
    banner = page.locator("#fp-update-banner")
    await banner.wait_for()
    assert "Find+ 1.3.0 is available." in await banner.inner_text()
    assert await page.locator("#fp-update-restart").count() == 0
    href = await banner.locator("a").get_attribute("href")
    assert href.endswith("/releases/tag/v1.3.0")


async def test_nothing_shows_while_up_to_date_or_still_downloading(page, base_url):
    await _open(page, base_url, _status(staged_version=None))  # the app is still downloading
    await page.wait_for_timeout(600)
    assert await page.locator("#fp-update-banner").count() == 0


async def test_settings_updates_section_states_the_request(page, base_url):
    await _open(page, base_url, _status())
    await page.click("#btn-settings")
    await page.wait_for_selector("#settings-modal[data-loaded='true']")
    await page.wait_for_function(
        "document.getElementById('update-status-line').textContent.includes('Installed')"
    )
    assert await page.inner_text("#fp-notice-update-check") == honesty.UPDATE_CHECK
    line = await page.inner_text("#update-status-line")
    assert "Installed: Find+ 1.2.1." in line and "Find+ 1.3.0 is downloaded" in line
    assert await page.is_visible("#btn-update-now")
    assert await page.is_checked("#setting-updates-auto")

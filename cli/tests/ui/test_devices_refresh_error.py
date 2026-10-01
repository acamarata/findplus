"""A failed "Refresh from your providers" shows in the Devices dialog itself (UAT finding 3).

The page banner sits behind the open dialog, so an error written there was
invisible. The dialog has its own error line (#device-modal-error).
"""

from __future__ import annotations

import pytest

from .test_devices_dialog_rate import _open_devices

pytestmark = pytest.mark.asyncio(loop_scope="session")

MESSAGE = "No provider is signed in"


async def test_refresh_failure_shows_inside_the_dialog(page, base_url):
    await page.route(
        "**/api/devices/refresh",
        lambda route: route.fulfill(status=400, json={"detail": MESSAGE}),
    )
    await _open_devices(page, base_url)
    await page.click("#btn-refresh-devices")
    line = page.locator("#device-modal-error")
    await line.wait_for(state="visible")
    assert MESSAGE in await line.inner_text()
    assert await page.locator("#device-modal-error").evaluate(
        "el => el.closest('#device-modal') !== null"
    )
    # Trying again clears the old message before the new request answers.
    await page.unroute("**/api/devices/refresh")
    await page.route(
        "**/api/devices/refresh",
        lambda route: route.fulfill(
            json={"found": 4, "providers": ["google-find-hub"], "errors": {}}
        ),
    )
    await page.click("#btn-refresh-devices")
    await page.wait_for_function(
        "() => document.getElementById('device-modal-error').textContent === ''"
    )

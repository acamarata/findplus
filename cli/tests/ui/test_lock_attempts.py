"""A wrong PIN says how many tries are left before the wait (UAT #15).

The lock screen said "Wrong PIN. Try again." and the five-try lockout arrived
without warning. The count now comes from /api/lock/status, never from the
server's own detail text.
"""

from __future__ import annotations

import json

import pytest

from .test_lock import PIN, _remove_pin, _set_pin_and_lock

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _wrong_pin(page, pin):
    await page.fill("#lock-pin", pin)
    await page.click("#lock-submit")
    await page.wait_for_function(
        "() => document.getElementById('lock-error').textContent.length > 0"
    )
    return await page.locator("#lock-error").inner_text()


async def test_wrong_pin_counts_down_the_remaining_tries(page, base_url):
    await _set_pin_and_lock(page, base_url)
    try:
        await page.goto(base_url + "/")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        first = await _wrong_pin(page, "000000")
        assert first == "Wrong PIN. 4 tries left before Find+ makes you wait."
        await page.fill("#lock-pin", "000001")
        await page.click("#lock-submit")
        await page.wait_for_function(
            "() => document.getElementById('lock-error').textContent.includes('3 tries')"
        )
        assert "findplus" not in await page.locator("#lock-error").inner_text()
    finally:
        # A right PIN clears the failure count the shared server keeps.
        await page.request.post(
            f"{base_url}/api/lock/unlock",
            data=json.dumps({"pin": PIN}),
            headers={"Content-Type": "application/json"},
        )
        await _remove_pin(page, base_url)

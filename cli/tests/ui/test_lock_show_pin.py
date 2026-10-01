"""The lock screen's Show PIN toggle, and the forgot-PIN text that matches reality."""

from __future__ import annotations

import contextlib

import pytest

from .test_lock import PIN
from .test_lock_purge import _setup_purge_fixture, _teardown_purge_fixture

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_show_pin_toggles_the_field_and_resets_on_the_next_lock(
    page, base_url, reset_alert_and_observation_state
):
    await _setup_purge_fixture(page, base_url)
    try:
        await page.goto(base_url + "/")
        await page.wait_for_selector("#app-shell[data-fp-ready='dashboard']")
        await page.locator("#btn-lock").dispatch_event("click")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        assert await page.get_attribute("#lock-pin", "type") == "password"
        await page.check("#lock-show-pin")
        assert await page.get_attribute("#lock-pin", "type") == "text"
        await page.fill("#lock-pin", PIN)
        await page.click("#lock-submit")
        await page.wait_for_selector("#lock-screen.hidden", state="attached")
        await page.locator("#btn-lock").dispatch_event("click")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        assert await page.get_attribute("#lock-pin", "type") == "password"
        assert not await page.is_checked("#lock-show-pin")
        await page.fill("#lock-pin", "000000")
        await page.click("#lock-submit")
        await page.locator("#lock-forgot summary").click()
        body = await page.locator("#lock-forgot").inner_text()
        assert "cannot recover a forgotten PIN" in body
    finally:
        with contextlib.suppress(Exception):
            await page.fill("#lock-pin", PIN)
            await page.click("#lock-submit")
        await _teardown_purge_fixture(page, base_url)

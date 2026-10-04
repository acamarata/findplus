"""PIN set/change/remove in Settings: the right order of checks (UAT #4)."""

from __future__ import annotations

import json

import pytest

from .test_settings_errors import PIN, _clear_pin_if_configured, _open_settings

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _with_pin(page, base_url) -> None:
    resp = await page.request.post(
        base_url + "/api/settings/pin",
        data=json.dumps({"new_pin": PIN}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, await resp.text()


async def test_removing_with_the_right_pin_asks_once_then_removes(page, base_url):
    await _with_pin(page, base_url)
    try:
        await _open_settings(page, base_url)
        await page.wait_for_selector("#lock-is-set:not(.hidden)")
        await page.fill("#current-pin", PIN)
        await page.click("#btn-remove-pin")
        dialog = page.locator("#fp-confirm-dialog[open]")
        await dialog.wait_for()
        assert "without a PIN" in await dialog.inner_text()
        await dialog.get_by_role("button", name="Remove").click()
        await page.wait_for_selector("#lock-not-set:not(.hidden)")
        assert "PIN removed" in await page.locator("#settings-message").inner_text()
    finally:
        await _clear_pin_if_configured(page, base_url)


async def test_a_short_new_pin_is_refused_beside_the_fields_and_never_sent(page, base_url):
    await _with_pin(page, base_url)
    sent: list[str] = []
    try:
        await _open_settings(page, base_url)
        await page.wait_for_selector("#lock-is-set:not(.hidden)")
        await page.route("**/api/settings/pin", lambda route: (sent.append("x"), route.abort()))
        await page.fill("#current-pin", PIN)
        await page.fill("#change-pin", "123")
        await page.click("#btn-change-pin")
        line = page.locator("#setting-change-pin-error")
        await line.wait_for(state="visible")
        assert "at least 6" in await line.inner_text()
        assert await page.get_attribute("#change-pin", "aria-invalid") == "true"
        assert sent == []
    finally:
        await _clear_pin_if_configured(page, base_url)


async def test_a_wrong_pin_is_checked_first_and_the_delete_is_never_sent(page, base_url):
    await _with_pin(page, base_url)
    calls: list[str] = []
    page.on("request", lambda r: calls.append(f"{r.method} {r.url.rsplit('/api', 1)[-1]}"))
    try:
        await _open_settings(page, base_url)
        await page.wait_for_selector("#lock-is-set:not(.hidden)")
        await page.fill("#current-pin", "000000")
        await page.click("#btn-remove-pin")
        await page.locator("#setting-change-pin-error").wait_for(state="visible")
        assert await page.locator("#fp-confirm-dialog[open]").count() == 0
        assert "POST /settings/pin/check" in calls
        assert "DELETE /settings/pin" not in calls
    finally:
        await _clear_pin_if_configured(page, base_url)


async def test_too_many_wrong_pins_say_so_beside_the_field(page, base_url):
    """The server's 429 (five wrong checks) is shown with the field, not up top."""
    await _with_pin(page, base_url)
    try:
        await _open_settings(page, base_url)
        await page.wait_for_selector("#lock-is-set:not(.hidden)")
        await page.route(
            "**/api/settings/pin/check",
            lambda route: route.fulfill(
                status=429,
                json={"detail": "Too many incorrect attempts. Try again in 60 seconds."},
            ),
        )
        await page.fill("#current-pin", PIN)
        await page.click("#btn-remove-pin")
        line = page.locator("#setting-change-pin-error")
        await line.wait_for(state="visible")
        assert "Too many incorrect attempts" in await line.inner_text()
        assert await page.get_attribute("#current-pin", "aria-invalid") == "true"
        assert await page.locator("#settings-message").inner_text() == ""
        assert await page.locator("#fp-confirm-dialog[open]").count() == 0
    finally:
        await page.unroute("**/api/settings/pin/check")
        await _clear_pin_if_configured(page, base_url)

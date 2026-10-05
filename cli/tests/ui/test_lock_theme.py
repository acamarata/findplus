"""The lock screen wears the SAVED theme, not the OS one (1.3, U25).

While locked every data route answers 401, so the app cannot read its settings.
The public GET /api/lock/status carries the saved theme instead, and the page
also keeps the last theme it used in localStorage. A fresh browser profile has no
cache, so the status answer alone must be enough: a dark OS with a light saved
theme shows a light lock screen, and the other way round.
"""

from __future__ import annotations

import contextlib
import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

PIN = "864213"
JSON_HEADERS = {"Content-Type": "application/json"}


async def _lock_with_theme(page, base_url, theme):
    await page.request.post(
        base_url + "/api/settings/pin", data=json.dumps({"new_pin": PIN}), headers=JSON_HEADERS
    )
    await page.request.patch(
        base_url + "/api/settings", data=json.dumps({"theme": theme}), headers=JSON_HEADERS
    )
    await page.request.post(base_url + "/api/lock/lock", headers=JSON_HEADERS)


async def _cleanup(page, base_url):
    with contextlib.suppress(Exception):
        await page.request.post(
            base_url + "/api/lock/unlock", data=json.dumps({"pin": PIN}), headers=JSON_HEADERS
        )
        await page.request.delete(
            base_url + "/api/settings/pin",
            data=json.dumps({"current_pin": PIN}),
            headers=JSON_HEADERS,
        )
        await page.request.patch(
            base_url + "/api/settings", data=json.dumps({"theme": "system"}), headers=JSON_HEADERS
        )


@pytest.mark.parametrize(("saved", "os_scheme"), [("light", "dark"), ("dark", "light")])
async def test_lock_screen_follows_the_saved_theme_with_no_cache(page, base_url, saved, os_scheme):
    try:
        await _lock_with_theme(page, base_url, saved)
        await page.emulate_media(color_scheme=os_scheme)
        await page.goto(base_url + "/")
        await page.evaluate("try { localStorage.clear() } catch (e) {}")
        await page.goto(base_url + "/")
        await page.wait_for_selector("#lock-screen:not(.hidden)")
        await page.wait_for_function(
            "(want) => document.documentElement.getAttribute('data-theme') === want", arg=saved
        )
        bg = await page.evaluate("getComputedStyle(document.getElementById('lock-screen')).backgroundColor")
        light_bg = "rgb(244, 246, 250)"
        assert (bg == light_bg) is (saved == "light"), (saved, bg)
    finally:
        await page.emulate_media(color_scheme="light")
        await _cleanup(page, base_url)

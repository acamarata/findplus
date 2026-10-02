"""The store-listing screenshots capture with the bundled Chromium (no real Chrome).

Proves packaging/scripts/gen-store-images.py's Playwright capture path works
against the seeded test server: the sign-in card and the localhost success
page, at 1280x800. Writes to a temp dir; the committed store images are the
deterministic icon/promo, not these captures.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


async def test_capture_signin_and_success_screenshots(page, base_url, tmp_path):
    await page.set_viewport_size({"width": 1280, "height": 800})

    await page.goto(base_url + "/#dashboard")
    await page.click("#btn-settings")
    await page.wait_for_selector("#fp-auth-google-card", timeout=15000)
    signin = tmp_path / "signin.png"
    await page.screenshot(path=str(signin))

    await page.goto(base_url + "/auth/google/success")
    await page.wait_for_selector("main.fp-helper", timeout=15000)
    success = tmp_path / "success.png"
    await page.screenshot(path=str(success))

    for shot in (signin, success):
        data = shot.read_bytes()
        assert data.startswith(PNG_MAGIC)
        assert len(data) > 1000

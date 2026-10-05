"""Poll Now while signed out finishes at once and says why (UAT finding 0)."""

from __future__ import annotations

import pytest

from ._live_helpers import open_dashboard

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_poll_now_signed_out_ends_polling_and_shows_the_reason(page, base_url):
    await open_dashboard(page, base_url)
    await page.click("#btn-poll")
    # Three trackers, no Google sign-in: no request leaves the machine, so the
    # answer must come back in seconds, not after a 10 s gap per tracker.
    await page.wait_for_function(
        "() => !document.getElementById('alert').textContent.includes('Polling')"
        " && document.getElementById('btn-poll').textContent === 'Poll now'",
        timeout=8000,
    )
    text = (await page.inner_text("#alert")).lower()
    assert "sign" in text, text
    assert await page.inner_text("#btn-poll") == "Poll now"

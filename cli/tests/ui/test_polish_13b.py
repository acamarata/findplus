"""Dashboard 1.3 polish: poll banner (U18) and the live dot word (U36).

The stopped-service banner is one line with Poll now; the Terminal hint sits in
a folded "Details"; Dismiss hides it for the session. The dot always has a
visible word and an aria-label.
"""

from __future__ import annotations

import pytest

from ._live_helpers import feed_for, open_dashboard, reload_status

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _stopped(page, base_url):
    feed = await feed_for(page, base_url)
    feed.cycle({}, 1, poller_running=False)
    await open_dashboard(page, base_url)
    await page.locator("#alert .alert-text").wait_for(state="visible")
    return feed


async def test_stopped_banner_is_one_line_with_folded_details(page, base_url):
    await _stopped(page, base_url)
    alert = page.locator("#alert")
    assert "may be stopped" in await alert.inner_text()
    assert await alert.locator(".alert-action").inner_text() == "Poll now"
    box = await alert.bounding_box()
    assert box["height"] < 60, box
    details = alert.locator("details.alert-details")
    assert await details.locator("summary").inner_text() == "Details"
    hint = details.locator("p")
    assert not await hint.is_visible()
    await details.locator("summary").click()
    assert "findplus start" in await hint.inner_text()
    assert await hint.is_visible()


async def test_stopped_banner_dismisses_for_the_session(page, base_url):
    await _stopped(page, base_url)
    await page.get_by_role("button", name="Dismiss").click()
    assert await page.locator("#alert").is_hidden()
    await reload_status(page)
    assert await page.locator("#alert").is_hidden()


async def test_live_dot_has_a_visible_word_and_label(page, base_url):
    await _stopped(page, base_url)
    word = page.locator("#live-word")
    assert (await word.inner_text()).strip() == "Stopped"
    assert await word.is_visible()
    label = await page.locator("#live-dot").get_attribute("aria-label")
    assert label and "stopped" in label.lower()
    feed = await feed_for(page, base_url)
    feed.cycle({}, 2, poller_running=True)
    await reload_status(page)
    assert (await word.inner_text()).strip() in {"Polling", "Idle", "Problem"}

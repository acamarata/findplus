"""The zero-new banner stays honest about re-sent fixes, failures and the next attempt (r1 #5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ._live_helpers import feed_for, open_dashboard

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _banner(page, base_url, statuses, **top) -> str:
    feed = await feed_for(page, base_url)
    feed.cycle(statuses, 300, observations_today=0, observations_total=0, **top)
    await open_dashboard(page, base_url)
    alert = page.locator("#alert.info")
    await alert.wait_for(state="visible")
    return await alert.inner_text()


async def test_a_timed_out_tracker_is_not_reported_as_the_same_place(page, base_url):
    text = await _banner(
        page,
        base_url,
        {"TAG-HOME": ("ok", 0), "TAG-AWAY": ("timeout", 0), "TAG-STALE": ("no_location", 0)},
    )
    assert "Away Tag did not answer" in text
    assert "No recent sighting: Stale Tag" in text
    assert "same place" not in text.lower()


async def test_duplicates_are_described_as_no_newer_locations(page, base_url):
    text = await _banner(page, base_url, {t: ("ok", 0) for t in ("TAG-HOME", "TAG-AWAY")})
    assert "Find Hub sent no newer locations" in text
    assert "same place" not in text.lower()


async def test_the_next_attempt_uses_the_real_time_not_the_normal_interval(page, base_url):
    due = (datetime.now(UTC) + timedelta(minutes=40)).isoformat().replace("+00:00", "Z")
    text = await _banner(
        page,
        base_url,
        {t: ("no_location", 0) for t in ("TAG-HOME", "TAG-AWAY", "TAG-STALE")},
        next_poll_at=due,
        poll_interval_minutes=5,
    )
    assert "asks again at" in text
    assert "every 5 minutes" not in text

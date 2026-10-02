"""Picking a never-seen tracker for a place asks nothing and logs nothing.

UAT #20: "Use a tracker" on a tracker with no observations called /api/latest,
whose expected 404 the browser logs as a red console error.
"""

from __future__ import annotations

import pytest

from ._roster17 import roster17

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_never_seen_tracker_makes_no_latest_request(page, base_url, ui_db, ui_env):
    asked: list[str] = []
    errors: list[str] = []
    page.on(
        "request",
        lambda r: asked.append(r.url) if "/api/latest" in r.url and "R17-05" in r.url else None,
    )
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    with roster17(ui_db, ui_env, tracked=10):
        await page.goto(base_url + "/")
        await page.wait_for_selector("#map.leaflet-container")
        await page.click('button[data-tab="places"]')
        await page.click("#fp-add-place-btn")
        await page.wait_for_selector(
            "#fp-place-tracker-select option[value='R17-05']", state="attached"
        )
        await page.select_option("#fp-place-tracker-select", "R17-05")
        await page.click("#fp-place-use-tracker-btn")
        await page.get_by_text("no location on record yet").wait_for()
    assert asked == []
    assert not [e for e in errors if "404" in e]

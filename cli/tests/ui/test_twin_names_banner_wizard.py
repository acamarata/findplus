"""Same-named trackers are told apart in the poll banner and the wizard rows (O11).

Roster (`_roster17.py`): R17-00 and R17-01 are both "Ali Pixel 8a" and tracked. The
server half (alert texts) is pinned in tests/alerts/test_dispatch_twin_names.py.
"""

# ruff: noqa: E501

from __future__ import annotations

import json

import pytest

from ._live_helpers import feed_for, open_dashboard
from ._roster17 import roster17
from ._signin_helpers import reply, status_body
from .conftest import SEEDED_COMPLETED_AT

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_poll_banner_names_the_twins_apart(page, base_url, ui_db, ui_env):
    with roster17(ui_db, ui_env, tracked=10):
        feed = await feed_for(page, base_url)
        feed.cycle(
            {"R17-00": ("no_location", 0), "R17-01": ("no_location", 0), "R17-05": ("ok", 0)},
            400,
            observations_today=0,
            observations_total=0,
        )
        await open_dashboard(page, base_url)
        text = await page.locator("#alert.info").inner_text()
        assert "Ali Pixel 8a (7-00)" in text and "Ali Pixel 8a (7-01)" in text
        assert "Tag 5" not in text


async def test_wizard_device_rows_name_the_twins_apart(page, base_url):
    twins = [
        {
            "device_id": f"{c}-{c}{c}{c}{c}",
            "name": "Twin Tag",
            "label": None,
            "icon": "letter",
            "color": None,
            "provider": "google-find-hub",
            "is_tracked": True,
        }
        for c in "ab"
    ]
    twins.append({**twins[0], "device_id": "solo", "name": "Solo Tag"})

    async def handler(route):
        body = {"devices": twins, "tracked_count": 3}
        await route.fulfill(json=body if route.request.method == "GET" else {})

    await page.route("**/api/auth/status", reply(status_body(google=True)))
    await page.route("**/api/devices", handler)
    await page.route("**/api/devices/refresh", reply({}))
    for key, value in (("onboarding.completed_at", None), ("onboarding.last_step", "devices")):
        await page.request.post(
            f"{base_url}/api/settings/{key}",
            data=json.dumps({"value": value}),
            headers={"Content-Type": "application/json"},
        )
    try:
        await page.goto(base_url + "/#/setup")
        await page.wait_for_selector("#fp-setup-devices-list [data-track]", timeout=15000)
        labels = await page.locator("[data-track]").evaluate_all(
            "(els) => els.map((e) => e.getAttribute('aria-label'))"
        )
        joined = " | ".join(labels)
        assert "Twin Tag (aaaa)" in joined and "Twin Tag (bbbb)" in joined
        assert "Solo Tag (" not in joined and "Solo Tag" in joined
        rows = await page.locator(
            ".fp-setup-device-row span:not(.fp-device-badge)"
        ).all_inner_texts()
        assert "Twin Tag (aaaa)" in rows and "Solo Tag" in rows
    finally:
        await page.request.post(
            f"{base_url}/api/settings/onboarding.completed_at",
            data=json.dumps({"value": SEEDED_COMPLETED_AT}),
            headers={"Content-Type": "application/json"},
        )
        await page.request.post(
            f"{base_url}/api/settings/onboarding.last_step",
            data=json.dumps({"value": None}),
            headers={"Content-Type": "application/json"},
        )

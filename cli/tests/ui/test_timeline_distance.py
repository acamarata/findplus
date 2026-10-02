"""The row after a flagged sighting is measured from the last trusted fix."""

# ruff: noqa: E501

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_distance_after_a_flagged_fix_is_from_the_last_trusted_one(trips_page, trips_server):
    p = trips_page
    await p.goto(trips_server["base"] + "/")
    got = await p.evaluate(
        """async () => {
          const m = await import('/static/app/timeline_distance.js');
          const a = {latitude: 40.0, longitude: -75.0, suspect: false, meters_from_previous: null};
          const bad = {latitude: 40.3, longitude: -75.0, suspect: true, meters_from_previous: 33000};
          const c = {latitude: 40.0, longitude: -75.0, suspect: false, meters_from_previous: 33000};
          const d = {latitude: 40.001, longitude: -75.0, suspect: false, meters_from_previous: 111};
          const pts = [a, bad, c, d];
          return [m.metersFromTrusted(pts, c), m.metersFromTrusted(pts, d), m.metersFromTrusted(pts, bad)];
        }"""
    )
    assert got[0] < 1, "the sighting after a flagged one sits where the tracker already was"
    assert got[1] == 111, "an ordinary row keeps the API's number"
    assert got[2] == 33000, "the flagged row itself is measured from the fix before it"

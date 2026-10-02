"""Did a tracker move? The motion half of person inference (spec § 3 step 2).

Purpose : Trackers do not move on their own, so a moved tracker was carried and
          a still one proves little. This module answers "carried, parked or
          can't tell" for one tracker's recent fixes, and when it last moved.
Inputs  : A tracker's fixes (anything with lat, lon, accuracy_meters and
          observed_at), a tz-aware `now`, InferParams (duck-typed: the
          motion_window_hours and min_motion_meters fields).
Outputs : A motion word, or the time of the latest move.
Constraints: Pure. Split out of people/infer.py (300-line cap).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import pairwise

from findplus.geo import haversine_meters

DEFAULT_ACC = 100.0


def moved(a, b, min_motion_meters: float) -> bool:
    """Two fixes further apart than max(min motion, 2 x the worse accuracy)."""
    acc = max(a.accuracy_meters or DEFAULT_ACC, b.accuracy_meters or DEFAULT_ACC)
    return haversine_meters(a.lat, a.lon, b.lat, b.lon) > max(min_motion_meters, 2 * acc)


def last_move_at(fixes, now: datetime, p) -> datetime | None:
    """When the latest move inside the motion window ended (the later fix), or None."""
    window_start = now - timedelta(hours=p.motion_window_hours)
    ordered = sorted(fixes, key=lambda f: f.observed_at)
    latest = None
    for prev, cur in pairwise(ordered):
        if cur.observed_at >= window_start and moved(prev, cur, p.min_motion_meters):
            latest = cur.observed_at
    return latest


def motion_of(fixes, now: datetime, p) -> str:
    """carried (moved within the window) | parked (still for the whole window) | unknown."""
    if last_move_at(fixes, now, p) is not None:
        return "carried"
    ordered = sorted(fixes, key=lambda f: f.observed_at)
    if len(ordered) >= 2 and ordered[-1].observed_at - ordered[0].observed_at >= timedelta(
        hours=p.motion_window_hours
    ):
        return "parked"
    return "unknown"

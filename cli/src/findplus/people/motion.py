"""Did a tracker move? The motion half of person inference (spec § 3 step 2).

Purpose : Trackers do not move on their own, so a moved tracker was carried and
          a still one proves little. This module answers "carried, parked or
          can't tell" for one tracker's recent fixes, and when it last moved.
Inputs  : A tracker's fixes (anything with lat, lon, accuracy_meters and
          observed_at), a tz-aware `now`, InferParams (duck-typed: the
          motion_window_hours, carried_minutes and min_motion_meters fields).
Outputs : A motion word, the time of the latest move, or whether the person
          moved on without the best cluster (MemberScore-like objects).
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
    """carried | settled | parked | unknown, scored from the LAST move.

    carried: moved within `carried_minutes` (45) of `now`. settled: moved within
    the window but still since (neutral, like unknown: a bag that came home an
    hour ago is no longer evidence that it is with the person). parked: still
    for the whole window. unknown: too few fixes to tell (review r116 #3).
    """
    last = last_move_at(fixes, now, p)
    if last is not None:
        recent = now - last <= timedelta(minutes=p.carried_minutes)
        return "carried" if recent else "settled"
    ordered = sorted(fixes, key=lambda f: f.observed_at)
    if len(ordered) >= 2 and ordered[-1].observed_at - ordered[0].observed_at >= timedelta(
        hours=p.motion_window_hours
    ):
        return "parked"
    return "unknown"


def moved_on_without_them(best: list, scores: list) -> bool:
    """No best-cluster tracker is being carried, and another tracker at least
    as trusted as any of them (reporting or gone quiet) moved later than all
    of them: the person went with that one, so the trackers left sitting say
    nothing about where they are (review r116 #1/#3). A lighter tracker moving
    later (a sibling took the bag) does not count, as in spec § 4.
    """
    if any(s.motion == "carried" for s in best):
        return False
    ids = {s.device_id for s in best}
    heaviest = max(s.weight for s in best)
    moves = [s.last_move_at for s in best if s.last_move_at is not None]
    latest = max(moves) if moves else None
    return any(
        s.last_move_at is not None
        and (latest is None or s.last_move_at > latest)
        and s.weight >= heaviest
        for s in scores
        if s.device_id not in ids
    )

"""Pure bad-coordinate rules (spec people-and-presence.md section 6.2).

Purpose    : Decide, from a fix and its neighbours, whether a sighting looks
             wrong. One function per rule; none touches the DB or the clock.
Inputs     : `Fix` values (id, time, position, accuracy) of one tracker, plus
             sibling trackers' fixes for `sibling_disagree`.
Outputs    : Booleans. `quality.score` combines them into a score and reasons.
Constraints: Every threshold is a named constant below. Raw fixes are never
             changed; a flagged fix is only left out of stays, trips, person
             inference and alerts. Two bad fixes in a row are kept (honest over
             clever): a rule needs two neighbours that agree with each other.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from datetime import timedelta

from findplus.geo import haversine_meters
from findplus.quality.fix import Fix

#: Bump when a rule or constant changes; `findplus db recompute-quality` rewrites rows.
ALGO_VERSION = 1

# Reason codes (stored comma-separated in observation_quality.reasons).
ABA_TELEPORT = "aba_teleport"
IMPOSSIBLE_SPEED = "impossible_speed"
EDGE_STRAY = "edge_stray"
JUMP_UNCONFIRMED = "jump_unconfirmed"
SIBLING_DISAGREE = "sibling_disagree"
LOW_ACCURACY = "low_accuracy"
CLOCK_SKEW = "clock_skew"
REASON_CODES = (
    ABA_TELEPORT,
    IMPOSSIBLE_SPEED,
    EDGE_STRAY,
    JUMP_UNCONFIRMED,
    SIBLING_DISAGREE,
    LOW_ACCURACY,
    CLOCK_SKEW,
)

#: 55 m/s is about 200 km/h: faster than a tag in a car on any road we expect.
MAX_SPEED_MPS = 55.0
#: aba_teleport: the neighbours must be this close in time, agree, and the jump be real.
ABA_WINDOW_S = 30 * 60
ABA_AGREE_RATIO = 0.5
ABA_MIN_JUMP_M = 500.0
ABA_ACCURACY_FACTOR = 2.0
ABA_MIN_ROUND_TRIP_MPS = 20.0
#: jump_unconfirmed: a fast, long hop from the previous fix with nothing after it yet.
JUMP_MIN_M = 1000.0
JUMP_MIN_MPS = 20.0
JUMP_WINDOW_S = 30 * 60
#: sibling_disagree: other trackers of the same person, each seen this recently.
SIBLING_WINDOW_S = 10 * 60
SIBLING_AGREE_M = 300.0
SIBLING_FAR_M = 1500.0
SIBLING_MIN_COUNT = 2
#: A tracker that has not moved by more than this "showed no motion".
STILL_RADIUS_M = 100.0
#: low_accuracy and clock_skew.
LOW_ACCURACY_M = 1000.0
CLOCK_SKEW_S = 5 * 60
#: Rescue: another fix this close (and recent) vouches for a suspect one.
RESCUE_OWN_WINDOW_S = 15 * 60
RESCUE_SIBLING_WINDOW_S = 10 * 60
RESCUE_MIN_M = 200.0
#: Fixes below this score are suspect.
SUSPECT_BELOW = 0.5
#: Score multipliers per reason (aba/speed/edge/jump/sibling are hard, the rest soft).
FACTORS: Mapping[str, float] = {
    ABA_TELEPORT: 0.2,
    IMPOSSIBLE_SPEED: 0.2,
    EDGE_STRAY: 0.3,
    JUMP_UNCONFIRMED: 0.4,
    SIBLING_DISAGREE: 0.3,
    LOW_ACCURACY: 0.5,
    CLOCK_SKEW: 0.8,
}
#: A rescued fix is not suspect, but it is not fully trusted either.
RESCUED_SCORE = 0.6
OWN_REPORT_BONUS = 1.1
_MIN_DT_S = 1.0


def dist(a: Fix, b: Fix) -> float:
    """Metres between two fixes (great circle)."""
    return haversine_meters(a.lat, a.lon, b.lat, b.lon)


def seconds(a: Fix, b: Fix) -> float:
    """Absolute seconds between two fixes."""
    return abs((b.t - a.t).total_seconds())


def speed(a: Fix, b: Fix) -> float:
    """Metres per second between two fixes (time floored at one second)."""
    return dist(a, b) / max(seconds(a, b), _MIN_DT_S)


def impossible_speed(prev: Fix, mid: Fix, nxt: Fix, max_speed: float = MAX_SPEED_MPS) -> bool:
    """Both legs above the ceiling and the neighbours agree: a one-fix spike."""
    if speed(prev, mid) <= max_speed or speed(mid, nxt) <= max_speed:
        return False
    return dist(prev, nxt) < ABA_AGREE_RATIO * min(dist(prev, mid), dist(mid, nxt))


def aba_teleport(prev: Fix, mid: Fix, nxt: Fix) -> bool:
    """The tracker jumps away and straight back: P and N agree, X is far and fast."""
    if seconds(prev, nxt) > ABA_WINDOW_S:
        return False
    d_in, d_out = dist(prev, mid), dist(mid, nxt)
    if dist(prev, nxt) >= ABA_AGREE_RATIO * min(d_in, d_out):
        return False
    if d_in <= max(ABA_MIN_JUMP_M, ABA_ACCURACY_FACTOR * (prev.acc + mid.acc)):
        return False
    return (d_in + d_out) / max(seconds(prev, nxt), _MIN_DT_S) > ABA_MIN_ROUND_TRIP_MPS


def edge_stray(edge: Fix, near: Fix, far: Fix, max_speed: float = MAX_SPEED_MPS) -> bool:
    """An end fix jumps away from two neighbours that agree with each other."""
    if speed(edge, near) <= max_speed:
        return False
    return dist(near, far) < ABA_AGREE_RATIO * dist(edge, near)


def is_jump(prev: Fix | None, fix: Fix) -> bool:
    """A long, fast hop from the previous fix (the precondition of jump_unconfirmed)."""
    if prev is None or seconds(prev, fix) > JUMP_WINDOW_S:
        return False
    return dist(prev, fix) > JUMP_MIN_M and speed(prev, fix) > JUMP_MIN_MPS


def is_corroborating(fix: Fix, other: Fix) -> bool:
    """`other` sits within max(200 m, fix accuracy) of `fix`: it vouches for it."""
    return dist(fix, other) <= max(RESCUE_MIN_M, fix.acc)


def sibling_disagree(fix: Fix, before: Sequence[Fix], near: Sequence[Fix]) -> bool:
    """Two or more other trackers of the person agree on a place far from `fix`.

    `before` is this tracker's own earlier fixes (newest last); `near` is the
    fix of each other tracker closest in time (see `nearest_in_time`). The
    tracker must have shown no motion before `fix`, otherwise it may simply
    have been carried away, and `fix` itself must be a jump away from where the
    tracker just was. A tracker that keeps reporting the SAME place while its
    siblings leave (a bag left at school) is not a bad coordinate: it is the
    left-behind case the people engine alerts on.
    """
    if not before or dist(fix, before[-1]) <= max(STILL_RADIUS_M, fix.acc):
        return False
    if len(before) >= 2 and dist(before[-1], before[-2]) > max(STILL_RADIUS_M, before[-1].acc):
        return False
    close = [s for s in near if seconds(fix, s) <= SIBLING_WINDOW_S]
    if len(close) < SIBLING_MIN_COUNT:
        return False
    if any(dist(a, b) > SIBLING_AGREE_M for a in close for b in close):
        return False
    return all(dist(fix, s) > SIBLING_FAR_M for s in close)


def nearest_in_time(times: Sequence[float], fixes: Sequence[Fix], at: Fix) -> Fix | None:
    """The fix closest in time to `at`; `times` is `[f.t.timestamp() for f in fixes]`, sorted."""
    if not fixes:
        return None
    i = bisect_left(times, at.t.timestamp())
    cands = [fixes[j] for j in (i - 1, i) if 0 <= j < len(fixes)]
    return min(cands, key=lambda f: seconds(at, f))


def low_accuracy(fix: Fix) -> bool:
    """The network reported a radius over a kilometre (soft: never suspect alone)."""
    return fix.accuracy_m is not None and fix.accuracy_m > LOW_ACCURACY_M


def clock_skew(fix: Fix) -> bool:
    """The sighting claims a time later than we first fetched it (plus slack)."""
    return fix.fetched_at is not None and fix.t > fix.fetched_at + timedelta(seconds=CLOCK_SKEW_S)

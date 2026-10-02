"""Drop single stray fixes that imply an impossible speed.

Purpose    : A crowd-sourced fix is sometimes far from where the tag really
             was. One such fix must not become a trip out and back.
Inputs     : Fixes sorted by time; the speed ceiling in metres per second.
Outputs    : (kept, dropped). Dropped fixes stay in the raw data; they are only
             left out of stays and trips, and the API lists them.
Constraints: A fix is an outlier only when BOTH legs to its neighbours exceed the
             ceiling AND the neighbours agree with each other (they are much
             closer to each other than to the stray). A real out-and-back trip
             with slow implied speed is never dropped. Only isolated strays are
             caught; two consecutive bad fixes are kept (honest over clever).
"""

from __future__ import annotations

from findplus.geo import haversine_meters
from findplus.trips.models import Fix

#: 55 m/s is about 200 km/h: faster than a tag in a car on any road we expect.
MAX_SPEED_MPS = 55.0
#: Treat two fixes closer in time than this as this far apart in time.
_MIN_DT_S = 1.0


def _dist(a: Fix, b: Fix) -> float:
    return haversine_meters(a.lat, a.lon, b.lat, b.lon)


def _speed(a: Fix, b: Fix) -> float:
    dt = max(abs((b.t - a.t).total_seconds()), _MIN_DT_S)
    return _dist(a, b) / dt


def _is_spike(prev: Fix, mid: Fix, nxt: Fix, max_speed: float) -> bool:
    """True when `mid` is a one-fix excursion that `prev` and `nxt` contradict."""
    if _speed(prev, mid) <= max_speed or _speed(mid, nxt) <= max_speed:
        return False
    legs = min(_dist(prev, mid), _dist(mid, nxt))
    return _dist(prev, nxt) < 0.5 * legs


def _edge_is_stray(edge: Fix, near: Fix, far: Fix, max_speed: float) -> bool:
    """An end fix is a stray when `near` and `far` agree and `edge` jumps away."""
    if _speed(edge, near) <= max_speed:
        return False
    return _dist(near, far) < 0.5 * _dist(edge, near)


def drop_outliers(
    fixes: list[Fix], max_speed: float = MAX_SPEED_MPS
) -> tuple[list[Fix], list[Fix]]:
    """Split `fixes` into (kept, dropped); order is preserved in both lists."""
    n = len(fixes)
    if n < 3:
        return list(fixes), []
    dropped_ids: set[int] = set()
    if _edge_is_stray(fixes[0], fixes[1], fixes[2], max_speed):
        dropped_ids.add(0)
    if _edge_is_stray(fixes[-1], fixes[-2], fixes[-3], max_speed):
        dropped_ids.add(n - 1)
    for i in range(1, n - 1):
        prev = fixes[i - 1]
        if (i - 1) in dropped_ids:  # judge against the last fix we trust
            prev = fixes[i - 2] if i >= 2 else prev
        if _is_spike(prev, fixes[i], fixes[i + 1], max_speed):
            dropped_ids.add(i)
    kept = [f for i, f in enumerate(fixes) if i not in dropped_ids]
    return kept, [f for i, f in enumerate(fixes) if i in dropped_ids]

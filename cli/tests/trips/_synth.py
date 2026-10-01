"""Synthetic days for the trips tests: no DB, no network, fixed clock."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from math import cos, radians

from findplus.trips.models import Fix

HOME = (41.1000, -80.1000)
SCHOOL = (41.1200, -80.0800)  # about 2.8 km from HOME
SHOP = (41.1100, -80.1300)
DAY0 = datetime(2026, 9, 18, 0, 0, tzinfo=UTC)


def offset(origin: tuple[float, float], north_m: float = 0.0, east_m: float = 0.0):
    """A point `north_m` / `east_m` metres from `origin`."""
    lat = origin[0] + north_m / 111_320.0
    lon = origin[1] + east_m / (111_320.0 * cos(radians(origin[0])))
    return lat, lon


class Day:
    """Builds fixes minute by minute; ids are unique and increasing."""

    def __init__(self, base: datetime = DAY0, seed: int = 7) -> None:
        self.base = base
        self.fixes: list[Fix] = []
        self.rng = random.Random(seed)

    def at(self, minute: float, point, acc: float | None = 50.0, jitter_m: float = 0.0) -> Fix:
        n, e = (self.rng.uniform(-jitter_m, jitter_m) for _ in range(2))
        lat, lon = offset(point, n, e)
        fix = Fix(len(self.fixes) + 1, self.base + timedelta(minutes=minute), lat, lon, acc)
        self.fixes.append(fix)
        return fix

    def stay(self, start: float, end: float, point, every: float = 10.0, **kw) -> None:
        minute = start
        while minute <= end:
            self.at(minute, point, **kw)
            minute += every


def hm(value) -> str:
    return value.strftime("%H:%M")


def home_lookup(lat: float, lon: float, acc: float):
    """A tiny stand-in for the saved places: Home and School, 200 m circles."""
    from findplus.geo import haversine_meters

    for place_id, name, pt in ((1, "Home", HOME), (2, "School", SCHOOL)):
        if haversine_meters(lat, lon, pt[0], pt[1]) <= 200:
            return place_id, name
    return None

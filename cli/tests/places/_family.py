"""Three synthetic weeks of a school-run family, for the "places we noticed" tests.

Purpose    : Fixes with realistic noise: Home at nights, School 8:10 to 15:00 on
             weekdays, Grandma's on Saturdays, and scattered bad at-home fixes.
Outputs    : `family_fixes()` -> {tracker name: [Fix]}; the three true points.
Constraints: Synthetic coordinates, fixed seed, UTC, no DB and no network.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

from findplus.trips.models import Fix
from tests.trips._synth import offset

HOME = (41.1000, -80.1000)
SCHOOL = (41.1200, -80.0800)
GRANDMA = (41.0500, -80.1500)
MIDWAY = (41.1100, -80.0900)
FIRST_MONDAY = date(2026, 9, 7)


def _stamp(day: date, hh: int, mm: int) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=UTC)


def _plan(day: date, child: bool) -> list[tuple[int, tuple[float, float]]]:
    """(minute of day, point) every 15 minutes."""
    sat, sun = day.weekday() == 5, day.weekday() == 6
    out = []
    for minute in range(0, 24 * 60, 15):
        point = HOME
        if child and not sat and not sun and 8 * 60 + 10 <= minute <= 15 * 60:
            point = SCHOOL
        elif child and not sat and not sun and minute in (8 * 60, 15 * 60 + 15):
            point = MIDWAY
        elif sat and 11 * 60 <= minute <= 15 * 60:
            point = GRANDMA
        out.append((minute, point))
    return out


def family_fixes(days: int = 21) -> dict[str, list[Fix]]:
    rng = random.Random(11)
    result: dict[str, list[Fix]] = {"Kai": [], "Mia": []}
    next_id = 1
    for d in range(days):
        day = FIRST_MONDAY + timedelta(days=d)
        for name in result:
            for minute, point in _plan(day, child=name == "Kai"):
                at_home = point == HOME
                spread, acc = (45.0, 40.0) if at_home else (25.0, 35.0)
                if at_home and rng.random() < 0.08:
                    spread, acc = 160.0, 120.0  # a bad at-home fix
                lat, lon = offset(point, rng.uniform(-spread, spread), rng.uniform(-spread, spread))
                when = _stamp(day, 0, 0) + timedelta(minutes=minute)
                result[name].append(Fix(next_id, when, lat, lon, acc))
                next_id += 1
    return result

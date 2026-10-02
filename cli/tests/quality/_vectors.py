"""Synthetic fixes for the quality tests: no DB, no network, fixed clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from findplus.trips.models import Fix
from tests.trips._synth import offset

#: A point in north-east Ohio; every vector is built from it by metre offsets.
ORIGIN = (41.1000, -80.1000)
T0 = datetime(2026, 9, 18, 4, 17, tzinfo=UTC)


def fix(i: int, minutes: float, north_m: float = 0.0, east_m: float = 0.0, acc: float = 30.0, **kw):
    """Fix number `i` at `minutes` after T0, `north_m`/`east_m` metres from ORIGIN."""
    lat, lon = offset(ORIGIN, north_m, east_m)
    return Fix(i, T0 + timedelta(minutes=minutes), lat, lon, acc, **kw)


def v1_owner_case() -> list[Fix]:
    """A 4:17, B 4:18 at 2.5 km, C 4:19 at 60 m from A."""
    return [fix(1, 0), fix(2, 1, 2500, acc=40), fix(3, 2, 60)]


def v2_real_drive() -> list[Fix]:
    """Home 8:00, 3 km at 8:06, 6 km at 8:12: about 8 m/s."""
    return [fix(1, 0), fix(2, 6, 3000), fix(3, 12, 6000)]


def v3_school_run() -> list[Fix]:
    """Home 7:40, school (3 km) 8:10, home 8:45."""
    return [fix(1, 0), fix(2, 30, 3000), fix(3, 65)]


def v4_two_bad_in_a_row() -> list[Fix]:
    """A, then two sightings at the same far place, then back home."""
    return [fix(1, 0), fix(2, 1, 2500), fix(3, 2, 2510), fix(4, 3, 20)]

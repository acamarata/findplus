"""Places we noticed: likely places found from long stays, never named for the owner.

Purpose    : Turn a few weeks of stays into candidate places ("a regular stop,
             8:10 AM to 3:00 PM on weekdays") so the owner only has to name them.
Inputs     : Stays per tracker name (trips.segment, dwell >= 45 min, non-suspect
             fixes only), the saved places, the dismissed spots, a local zone.
Outputs    : Candidate dicts: lat, lon, radius_m, visits, days, nights, typical,
             kind_guess ("home" | "school_or_work" | "regular"), trackers.
Constraints: Pure; no DB, clock or network. Coordinates come from the data only.
             A guess is a question ("Home?"), never a name. A spot inside a saved
             place's circle, or near a dismissed spot, is left out. A spot needs
             stays on MIN_DAYS different days.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from statistics import median
from zoneinfo import ZoneInfo

from findplus.geo import haversine_meters
from findplus.trips.models import Stay

MIN_STAY_MIN = 45.0
MERGE_M = 100.0
DISMISS_M = 150.0
MIN_DAYS = 3
MIN_RADIUS_M, MAX_RADIUS_M = 100, 250
NIGHT_MIN = 120
#: Stays longer than this are cut at local midnights so a long weekend at home is not one visit.
SPLIT_AFTER_H = 18.0


@dataclass
class _Spot:
    lat: float
    lon: float
    weight: float = 0.0
    stays: list[tuple[str, Stay]] = field(default_factory=list)

    def add(self, name: str, stay: Stay) -> None:
        w = max(stay.duration_min, 1.0)
        total = self.weight + w
        self.lat = (self.lat * self.weight + stay.lat * w) / total
        self.lon = (self.lon * self.weight + stay.lon * w) / total
        self.weight = total
        self.stays.append((name, stay))


def _cluster(items: list[tuple[str, Stay]]) -> list[_Spot]:
    spots: list[_Spot] = []
    for name, stay in sorted(items, key=lambda it: it[1].start):
        near = [(haversine_meters(s.lat, s.lon, stay.lat, stay.lon), s) for s in spots]
        near = [pair for pair in near if pair[0] <= MERGE_M]
        if near:
            min(near, key=lambda pair: pair[0])[1].add(name, stay)
        else:
            spot = _Spot(stay.lat, stay.lon)
            spot.add(name, stay)
            spots.append(spot)
    return spots


def _local_midnights(start: datetime, end: datetime, tz: ZoneInfo):
    day = start.astimezone(tz).date() + timedelta(days=1)
    while True:
        cut = datetime.combine(day, time(0), tz)
        if cut >= end:
            return
        yield cut
        day += timedelta(days=1)


def _intervals(spot: _Spot, tz: ZoneInfo) -> list[tuple[datetime, datetime]]:
    """Stays from every tracker merged where they overlap: one visit, however many tags came."""
    raw = sorted((s.start, s.end) for _, s in spot.stays)
    merged: list[list[datetime]] = []
    for a, b in raw:
        if merged and a <= merged[-1][1] + timedelta(minutes=30):
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out: list[tuple[datetime, datetime]] = []
    for a, b in merged:
        if (b - a).total_seconds() <= SPLIT_AFTER_H * 3600:
            out.append((a, b))
            continue
        cuts = [a, *_local_midnights(a, b, tz), b]
        out.extend(pairwise(cuts))
    return out


def _nights(intervals, tz: ZoneInfo) -> set[date]:
    """Local dates whose 00:00 to 05:00 was mostly spent at this spot."""
    found: set[date] = set()
    for a, b in intervals:
        day = a.astimezone(tz).date()
        while datetime.combine(day, time(0), tz) < b:
            lo = max(a, datetime.combine(day, time(0), tz))
            hi = min(b, datetime.combine(day, time(5), tz))
            if (hi - lo).total_seconds() / 60.0 >= NIGHT_MIN:
                found.add(day)
            day += timedelta(days=1)
    return found


def _minute_of_day(value: datetime, tz: ZoneInfo) -> int:
    local = value.astimezone(tz)
    return local.hour * 60 + local.minute


def _typical(intervals, tz: ZoneInfo) -> dict:
    weekday = sum(1 for a, _ in intervals if a.astimezone(tz).weekday() < 5)
    share = weekday / len(intervals)
    days = "weekdays" if share >= 0.8 else "weekends" if share <= 0.2 else "every_day"
    return {
        "days": days,
        "start_min": round(median(_minute_of_day(a, tz) for a, _ in intervals)),
        "end_min": round(median(_minute_of_day(b, tz) for _, b in intervals)),
    }


def _radius(spot: _Spot) -> int:
    reach = max(
        haversine_meters(spot.lat, spot.lon, s.lat, s.lon) + s.radius_m for _, s in spot.stays
    )
    return int(min(MAX_RADIUS_M, max(MIN_RADIUS_M, -(-reach // 10) * 10)))


def _candidate(spot: _Spot, tz: ZoneInfo) -> dict | None:
    intervals = _intervals(spot, tz)
    days = {a.astimezone(tz).date() for a, _ in intervals}
    days |= {(b - timedelta(seconds=1)).astimezone(tz).date() for _, b in intervals}
    if len(days) < MIN_DAYS:
        return None
    return {
        "lat": round(spot.lat, 6),
        "lon": round(spot.lon, 6),
        "radius_m": _radius(spot),
        "visits": len(intervals),
        "days": len(days),
        "nights": len(_nights(intervals, tz)),
        "typical": _typical(intervals, tz),
        "kind_guess": "regular",
        "trackers": sorted({name for name, _ in spot.stays}),
    }


def _guess_kinds(cands: list[dict], has_home: bool) -> None:
    sleepy = [c for c in cands if c["nights"] >= MIN_DAYS]
    if sleepy and not has_home:
        max(sleepy, key=lambda c: (c["nights"], c["visits"]))["kind_guess"] = "home"
    for c in cands:
        t = c["typical"]
        daytime = 5 * 60 <= t["start_min"] <= 12 * 60 and t["end_min"] > t["start_min"] + 180
        if c["kind_guess"] == "regular" and t["days"] == "weekdays" and daytime:
            c["kind_guess"] = "school_or_work"


def _near(spot: _Spot, circles: list[tuple[float, float, float]]) -> bool:
    return any(haversine_meters(spot.lat, spot.lon, la, lo) <= r for la, lo, r in circles)


def find_candidates(
    stays_by_tracker: dict[str, list[Stay]],
    tz: ZoneInfo,
    saved: list[tuple[float, float, float]] = (),
    dismissed: list[tuple[float, float]] = (),
    has_home: bool = False,
) -> list[dict]:
    """Likely places, the overnight one first, then by visits. `saved` is (lat, lon, radius_m)."""
    items = [
        (name, s)
        for name, stays in stays_by_tracker.items()
        for s in stays
        if s.duration_min >= MIN_STAY_MIN
    ]
    skip = [*saved, *((la, lo, DISMISS_M) for la, lo in dismissed)]
    found = [
        c
        for spot in _cluster(items)
        if not _near(spot, skip) and (c := _candidate(spot, tz)) is not None
    ]
    _guess_kinds(found, has_home)
    found.sort(key=lambda c: (c["kind_guess"] != "home", -c["visits"], -c["days"]))
    return found

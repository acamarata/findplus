"""Working context for one day's summary: windows, places, lead tracker (spec § 7.1).

Purpose    : Everything `people/day.py` needs to look things up while it builds
             lines: the day's UTC bounds, fixes per tracker inside the day, a
             pure place lookup, the lead tracker and the "around" test.
Inputs     : A DayInput.
Outputs    : `Ctx`, built by `make_ctx`.
Constraints: Pure. A tracker with a confirmed left-behind episode never leads
             the day and its sightings never count as the person's own.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from findplus.geo import haversine_meters
from findplus.people.day_text import APPROX_MINUTES, via_text
from findplus.people.day_types import DayInput, PlaceIn
from findplus.quality.fix import Fix
from findplus.timeline import day_bounds_utc

#: How far a sighting may sit outside a place's circle and still count (accuracy cap).
_ACC_CAP_M = 100.0


@dataclass
class Ctx:
    inp: DayInput
    start: datetime
    end: datetime
    places: dict[int, PlaceIn]
    labels: dict[str, str]
    #: device_id -> fixes with start <= t < end, oldest first.
    window: dict[str, list[Fix]]
    #: (device_id, started, cleared-or-None) of confirmed left-behind episodes.
    apart: list[tuple[str, datetime, datetime | None]]
    lead: str | None = None

    @property
    def tz(self):
        return self.inp.tz

    def place_at(self, fix: Fix) -> PlaceIn | None:
        """The closest saved place whose circle holds this sighting, else None."""
        best = None
        for place in self.places.values():
            d = haversine_meters(fix.lat, fix.lon, place.lat, place.lon)
            if d <= place.radius_m + min(fix.acc, _ACC_CAP_M) and (best is None or d < best[0]):
                best = (d, place)
        return best[1] if best else None

    def lookup(self, lat: float, lon: float, acc: float):
        place = self.place_at(Fix(0, self.start, lat, lon, acc))
        return (place.id, place.name) if place else None

    def is_apart(self, device_id: str, t: datetime) -> bool:
        return any(d == device_id and s <= t and (c is None or t < c) for d, s, c in self.apart)

    def person_fixes(self) -> list[tuple[Fix, str]]:
        """The day's sightings of trackers that were with the person, oldest first."""
        rows = [
            (f, d) for d, fixes in self.window.items() for f in fixes if not self.is_apart(d, f.t)
        ]
        return sorted(rows, key=lambda r: (r[0].t, r[0].id))

    def fix_near(self, device_id: str | None, t: datetime) -> Fix | None:
        """That tracker's latest sighting at or before `t`, else any tracker's."""
        pool = self.inp.fixes.get(device_id or "", ())
        past = [f for f in pool if f.t <= t]
        if not past:
            past = [f for fixes in self.inp.fixes.values() for f in fixes if f.t <= t]
        return max(past, key=lambda f: (f.t, f.id)) if past else None

    def around(self, t: datetime, device_ids=()) -> bool:
        """True when the sighting before `t` was over APPROX_MINUTES earlier (or none)."""
        ids = [d for d in device_ids if d in self.inp.fixes] or list(self.inp.fixes)
        before = [f.t for d in ids for f in self.inp.fixes[d] if f.t < t]
        return not before or (t - max(before)) > timedelta(minutes=APPROX_MINUTES)

    def around_after(self, t: datetime, device_ids=()) -> bool:
        """True when the next sighting after `t` is over APPROX_MINUTES later."""
        ids = [d for d in device_ids if d in self.inp.fixes] or list(self.inp.fixes)
        after = [f.t for d in ids for f in self.inp.fixes[d] if f.t > t]
        return bool(after) and (min(after) - t) > timedelta(minutes=APPROX_MINUTES)

    def via(self, device_ids) -> str:
        return via_text(device_ids, self.labels)


def _choose_lead(inp: DayInput, window, apart_ids: set[str]) -> str | None:
    """The tracker the day's stays follow: the events' usual lead, else the heaviest."""
    counts = Counter(
        e.lead_device_id
        for e in inp.events
        if e.lead_device_id and e.lead_device_id not in apart_ids
    )
    if counts:
        weight = {t.device_id: t.weight for t in inp.trackers}
        return max(counts, key=lambda d: (counts[d], weight.get(d, 0.0), d))
    pool = [t for t in inp.trackers if window.get(t.device_id) and t.device_id not in apart_ids]
    if not pool:
        return None
    return max(pool, key=lambda t: (t.weight, len(window[t.device_id]), t.device_id)).device_id


def make_ctx(inp: DayInput) -> Ctx:
    start, end = day_bounds_utc(inp.day, inp.tz)
    window = {d: [f for f in fixes if start <= f.t < end] for d, fixes in inp.fixes.items()}
    apart = [(e.device_id, e.started, e.cleared_at) for e in inp.episodes if e.confirmed_at]
    ctx = Ctx(
        inp=inp,
        start=start,
        end=end,
        places={p.id: p for p in inp.places},
        labels={t.device_id: t.label for t in inp.trackers},
        window=window,
        apart=apart,
    )
    ctx.lead = _choose_lead(inp, window, {a[0] for a in apart})
    return ctx

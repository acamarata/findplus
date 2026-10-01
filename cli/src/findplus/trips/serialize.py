"""JSON shapes for stays, trips, gaps and dropped fixes.

Purpose    : One place that decides what the API, CLI --json and MCP return.
Inputs     : Segmentation objects and an optional display zone.
Outputs    : Plain dicts. Distances are metres rounded to 10 and always sit
             next to `distance_approximate: true` so no client can present
             them as a road distance.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from findplus.trips.models import Fix, Gap, Stay, TripLeg, iso_local, iso_utc


def _times(prefix_start, prefix_end, start, end, tz) -> dict[str, Any]:
    return {
        prefix_start: iso_utc(start),
        prefix_end: iso_utc(end),
        prefix_start.replace("_at", "_local"): iso_local(start, tz),
        prefix_end.replace("_at", "_local"): iso_local(end, tz),
    }


def fix_dict(fix: Fix, tz: ZoneInfo | None = None) -> dict[str, Any]:
    return {
        "observation_id": fix.id,
        "at": iso_utc(fix.t),
        "local": iso_local(fix.t, tz),
        "latitude": fix.lat,
        "longitude": fix.lon,
        "accuracy_meters": fix.accuracy_m,
    }


def stay_dict(stay: Stay, tz: ZoneInfo | None = None) -> dict[str, Any]:
    return {
        "id": stay.id,
        "label": stay.label,
        "place_id": stay.place_id,
        "place_name": stay.place_name,
        **_times("start_at", "end_at", stay.start, stay.end, tz),
        "duration_minutes": round(stay.duration_min, 1),
        "latitude": stay.lat,
        "longitude": stay.lon,
        "radius_meters": stay.radius_m,
        "fix_count": stay.fix_count,
        "longest_gap_minutes": round(stay.longest_gap_min, 1),
    }


def trip_dict(trip: TripLeg, stays: dict[str, Stay], tz: ZoneInfo | None = None) -> dict[str, Any]:
    def end_of(stay_id: str | None) -> dict[str, Any] | None:
        s = stays.get(stay_id or "")
        return {"stay_id": s.id, "label": s.label, "place_id": s.place_id} if s else None

    return {
        "id": trip.id,
        **_times("start_at", "end_at", trip.start, trip.end, tz),
        "duration_minutes": round(trip.duration_min, 1),
        "from": end_of(trip.from_stay),
        "to": end_of(trip.to_stay),
        "distance_meters": int(round(trip.distance_m, -1)),
        "distance_approximate": True,
        "fix_count": trip.fix_count,
        "longest_gap_minutes": round(trip.longest_gap_min, 1),
        "points": [fix_dict(p, tz) for p in trip.points],
    }


def gap_dict(gap: Gap, tz: ZoneInfo | None = None) -> dict[str, Any]:
    return {
        **_times("start_at", "end_at", gap.start, gap.end, tz),
        "minutes": round(gap.minutes, 1),
        "inside": gap.inside,
    }

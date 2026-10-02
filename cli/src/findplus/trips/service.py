"""Load observations for a device and range, segment them, build the payload.

Purpose    : The DB-facing half of trips, shared by the API, CLI and MCP tool.
Inputs     : A session, device id, start date, number of days, zone, thresholds.
Outputs    : The `/api/trips` payload dict (see `trips_payload`).
Constraints: One device per call, never merged across devices (invariant 5).
             Day bounds come from `findplus.timeline.day_bounds_utc`, so DST
             days are 23 or 25 hours, not 24. Read-only; no network.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from findplus import honesty
from findplus.places.geofence import PlaceSpec, classify_point
from findplus.places.repo import list_places
from findplus.quality.store import verdicts_for
from findplus.timeline import day_bounds_utc, fetch_observations
from findplus.trips.models import Fix, iso_local, iso_utc
from findplus.trips.segment import Segmentation, SegmentParams, segment
from findplus.trips.serialize import fix_dict, gap_dict, stay_dict, trip_dict

MAX_DAYS = 31


def place_lookup(session: Session):
    """A lookup (lat, lon, accuracy) -> (place_id, name) for the closest containing place."""
    specs = [
        (
            PlaceSpec(
                p.id,
                p.latitude_e7,
                p.longitude_e7,
                p.radius_meters,
                p.enter_confirmations,
                p.exit_confirmations,
            ),
            p.name,
        )
        for p in list_places(session)
    ]

    def lookup(lat: float, lon: float, acc: float):
        best = None
        for spec, name in specs:
            c = classify_point(spec, lat, lon, acc)
            if c.side == "inside" and (best is None or c.distance_meters < best[0]):
                best = (c.distance_meters, spec.id, name)
        return (best[1], best[2]) if best else None

    return lookup


def load_fixes(session: Session, device_id: str, start_day: date, days: int, tz: ZoneInfo):
    """(fixes, start_utc, end_utc) for `days` local days beginning `start_day`."""
    start_utc, _ = day_bounds_utc(start_day, tz)
    _, end_utc = day_bounds_utc(start_day + timedelta(days=days - 1), tz)
    rows = fetch_observations(session, device_id, start_utc, end_utc)
    fixes = [Fix(r.id, r.observed_at, r.latitude, r.longitude, r.accuracy_meters) for r in rows]
    return fixes, start_utc, end_utc


def segmentation_for(
    session: Session,
    device_id: str,
    start_day: date,
    days: int,
    tz: ZoneInfo,
    params: SegmentParams | None = None,
) -> tuple[Segmentation, list[Fix]]:
    """Run `segment` on the stored fixes for the range; also return the fixes."""
    fixes, _, _ = load_fixes(session, device_id, start_day, max(1, min(days, MAX_DAYS)), tz)
    verdicts = verdicts_for(session, [f.id for f in fixes])
    return segment(fixes, params, place_lookup(session), verdicts), fixes


def trips_payload(
    seg: Segmentation,
    fixes: list[Fix],
    *,
    device_id: str,
    start_day: date,
    days: int,
    tz: ZoneInfo,
    params: SegmentParams,
    routing_enabled: bool = False,
) -> dict[str, Any]:
    """The documented response body. `label` is the honesty sentence for this view."""
    stay_by_id = {s.id: s for s in seg.stays}
    ordered = sorted(fixes, key=lambda f: (f.t, f.id))
    return {
        "device_id": device_id,
        "date": start_day.isoformat(),
        "days": days,
        "timezone": str(tz),
        "label": honesty.TRIPS_APPROXIMATE,
        "stays": [stay_dict(s, tz) for s in seg.stays],
        "trips": [trip_dict(t, stay_by_id, tz) for t in seg.trips],
        "gaps": [gap_dict(g, tz) for g in seg.gaps],
        "outliers": [fix_dict(f, tz, seg.reasons.get(f.id, ())) for f in seg.dropped],
        "fix_count": seg.fix_count,
        "first_fix_at": iso_utc(ordered[0].t) if ordered else None,
        "last_fix_at": iso_utc(ordered[-1].t) if ordered else None,
        "first_fix_local": iso_local(ordered[0].t, tz) if ordered else None,
        "last_fix_local": iso_local(ordered[-1].t, tz) if ordered else None,
        "parameters": {
            "dwell_minutes": params.dwell_min,
            "min_radius_meters": params.min_radius_m,
            "accuracy_factor": params.accuracy_factor,
            "gap_minutes": params.gap_min,
        },
        "routing_enabled": routing_enabled,
    }


def trips_for(
    session: Session,
    device_id: str,
    start_day: date,
    days: int,
    tz: ZoneInfo,
    *,
    gap_min: float | None = None,
    routing_enabled: bool = False,
) -> dict[str, Any]:
    """Segment and serialise one device's range; the one call every surface makes."""
    days = max(1, min(days, MAX_DAYS))
    params = SegmentParams() if gap_min is None else SegmentParams(gap_min=gap_min)
    seg, fixes = segmentation_for(session, device_id, start_day, days, tz, params)
    return trips_payload(
        seg,
        fixes,
        device_id=device_id,
        start_day=start_day,
        days=days,
        tz=tz,
        params=params,
        routing_enabled=routing_enabled,
    )

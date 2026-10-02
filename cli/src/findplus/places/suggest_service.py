"""Places we noticed: load the history, find the candidates, remember "Not a place".

Purpose    : The DB half of `places.suggest`, shared by the API and the CLI.
Inputs     : A session, the number of local days to look back, a zone.
Outputs    : `{"candidates": [...]}` (see suggest.find_candidates) and the
             dismissed list kept in the `places.suggest.dismissed` setting.
Constraints: Read-only apart from `dismiss`. One tracker at a time through
             `trips.segment` (never merged), with the stored quality verdicts,
             so bad-coordinate fixes never make a place. A tracker with no
             history is skipped; no network.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Device, LocationObservation
from findplus.device_labels import unique_names
from findplus.places.repo import list_places
from findplus.places.suggest import MIN_STAY_MIN, find_candidates
from findplus.state import get_setting, set_setting
from findplus.trips.segment import SegmentParams
from findplus.trips.service import segmentation_for

DISMISSED_KEY = "places.suggest.dismissed"
LOOKBACK_DAYS = 30
MAX_DISMISSED = 200


def dismissed_spots(session: Session) -> list[tuple[float, float]]:
    try:
        rows = json.loads(get_setting(session, DISMISSED_KEY) or "[]")
        return [(float(r[0]), float(r[1])) for r in rows]
    except (ValueError, TypeError, IndexError):
        return []


def dismiss(session: Session, lat: float, lon: float) -> int:
    """Remember a spot as "not a place". Returns how many spots are remembered."""
    spots = [*dismissed_spots(session), (round(lat, 6), round(lon, 6))][-MAX_DISMISSED:]
    set_setting(session, DISMISSED_KEY, json.dumps(spots))
    return len(spots)


def _device_ids(session: Session) -> list[str]:
    rows = session.execute(select(LocationObservation.device_id).distinct()).all()
    known = set(session.scalars(select(Device.device_id)))
    return sorted(r[0] for r in rows if r[0] in known)


def suggestions(session: Session, tz: ZoneInfo, *, today=None, days: int = LOOKBACK_DAYS) -> dict:
    """The candidates for the last `days` local days, never merged across trackers' own stays."""
    today = today or datetime.now(tz).date()
    start = today - timedelta(days=days - 1)
    names = unique_names(session)
    params = SegmentParams(dwell_min=MIN_STAY_MIN)
    stays = {}
    for device_id in _device_ids(session):
        seg, _ = segmentation_for(session, device_id, start, days, tz, params)
        stays.setdefault(names.get(device_id, device_id), []).extend(seg.stays)
    places = list_places(session)
    saved = [(p.latitude_e7 / 1e7, p.longitude_e7 / 1e7, float(p.radius_meters)) for p in places]
    found = find_candidates(
        stays, tz, saved, dismissed_spots(session), has_home=any(p.kind == "home" for p in places)
    )
    return {"candidates": found}

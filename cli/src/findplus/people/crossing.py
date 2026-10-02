"""When did the person cross? The first sighting on the new side (spec § 5.1, review r116 #2/#9).

Purpose : A person EXIT waits for the tracker's own geofence to confirm (two
          outside fixes, D17), so the evaluation that decides it runs one
          sighting after the crossing. The event must carry the crossing time,
          not the confirming one: "left Home at 7:40", the first sighting
          outside, and the tracker that was seen there (whose report time and
          lag the alert then quotes).
Inputs  : A session, the PersonFix that decided the transition, the place, the
          target side, and the window (the last person transition, `as_of`).
Outputs : (device_id, observed_at) of the deciding tracker's first sighting on
          the target side, or None when no supporter has one.
Constraints: Read only. Suspect sightings never count (people/_quality.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import LocationObservation
from findplus.geo import haversine_meters
from findplus.people import _quality
from findplus.people.infer import PersonFix, PlaceRef
from findplus.places.geofence import exit_margin

#: How far back a crossing is searched when the person never transitioned.
LOOKBACK_HOURS = 6


def near(place: PlaceRef, fix) -> bool:
    """The sighting itself is not clearly outside the place (geofence's own band)."""
    if fix is None:
        return False
    d = haversine_meters(place.latitude_e7 / 1e7, place.longitude_e7 / 1e7, fix.lat, fix.lon)
    acc = fix.accuracy_meters if fix.accuracy_meters is not None else 100.0
    return d <= place.radius_meters + max(acc, exit_margin(place.radius_meters))


def _on_side(place: PlaceRef, o: LocationObservation, target: str) -> bool:
    fix = _Fix(o.latitude_e7 / 1e7, o.longitude_e7 / 1e7, o.accuracy_meters)
    return near(place, fix) if target == "inside" else not near(place, fix)


class _Fix:
    __slots__ = ("accuracy_meters", "lat", "lon")

    def __init__(self, lat: float, lon: float, acc: float | None) -> None:
        self.lat, self.lon, self.accuracy_meters = lat, lon, acc


def first_on_side(
    session: Session, device_id: str, place: PlaceRef, target: str, lo: datetime, as_of: datetime
) -> datetime | None:
    """The earliest sighting of an unbroken run on `target`'s side ending at `as_of`."""
    rows = session.scalars(
        select(LocationObservation)
        .where(
            LocationObservation.device_id == device_id,
            LocationObservation.observed_at > lo,
            LocationObservation.observed_at <= as_of,
        )
        .order_by(LocationObservation.observed_at.desc())
    ).all()
    suspect = _quality.suspect_ids(session, [device_id], lo, as_of)
    first = None
    for o in rows:
        if o.id in suspect:
            continue
        if not _on_side(place, o, target):
            break
        first = o.observed_at
    return first


def crossing(
    session: Session,
    fix: PersonFix,
    place: PlaceRef,
    target: str,
    since: datetime | None,
    as_of: datetime,
) -> tuple[str, datetime] | None:
    """The deciding tracker (the lead first, then the other supporters) and the
    first sighting of its run on the new side, after the last transition."""
    lo = as_of - timedelta(hours=LOOKBACK_HOURS)
    if since is not None and since > lo:
        lo = since
    order = [fix.lead_device_id, *[d for d in fix.supporters if d != fix.lead_device_id]]
    for device_id in [d for d in order if d]:
        when = first_on_side(session, device_id, place, target, lo, as_of)
        if when is not None:
            return device_id, when
    return None

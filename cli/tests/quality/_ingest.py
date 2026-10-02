"""Builders for the quality ingest tests: one or more trackers, places, polls.

Every fix goes through the real ingest -> quality -> geofence -> person chain.
Synthetic data only; no network, no real account, no real ~/.findplus.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from findplus.db.models import LocationObservation, Place, PlaceEvent
from findplus.db.models_people import ObservationQuality
from findplus.ingest import ingest_observations, upsert_device
from findplus.places.repo import create_place
from tests.conftest import make_observation
from tests.quality._vectors import ORIGIN
from tests.trips._synth import offset

START = datetime(2026, 9, 18, 4, 17, tzinfo=UTC)
#: Seconds between a sighting and the poll that fetched it, unless a test says otherwise.
FETCH_LAG_S = 20


def at(minutes: float) -> datetime:
    return START + timedelta(minutes=minutes)


def add_place(session, name: str, north_m: float = 0.0, east_m: float = 0.0, radius: int = 200):
    lat, lon = offset(ORIGIN, north_m, east_m)
    return create_place(
        session,
        name=name,
        latitude_e7=round(lat * 1e7),
        longitude_e7=round(lon * 1e7),
        radius_meters=radius,
    )


def add_tracker(session, device_id: str) -> None:
    upsert_device(session, device_id, device_id, now=START - timedelta(days=1))


def obs(device: str, minutes: float, north_m: float = 0.0, east_m: float = 0.0, acc: float = 30.0):
    lat, lon = offset(ORIGIN, north_m, east_m)
    when = at(minutes)
    return make_observation(
        device_id=device, device_name=device, lat=lat, lon=lon, observed_at=when, accuracy=acc
    )


def poll(session, device: str, minutes: float, north_m: float = 0.0, east_m: float = 0.0, **kw):
    """One poll that returns one new sighting, fetched FETCH_LAG_S after it was seen."""
    lag = kw.pop("lag_s", FETCH_LAG_S)
    ob = obs(device, minutes, north_m, east_m, **kw)
    ingest_observations(session, [ob], fetched_at=ob.observed_at + timedelta(seconds=lag))
    session.flush()


def events(session, place: str, kind: str = "ENTER", device: str | None = None) -> list:
    pid = session.scalar(select(Place.id).where(Place.name == place))
    stmt = select(PlaceEvent).where(PlaceEvent.place_id == pid, PlaceEvent.event_type == kind)
    if device:
        stmt = stmt.where(PlaceEvent.device_id == device)
    return list(session.scalars(stmt.order_by(PlaceEvent.observed_at)))


def verdict(session, device: str, minutes: float) -> ObservationQuality | None:
    oid = session.scalar(
        select(LocationObservation.id).where(
            LocationObservation.device_id == device, LocationObservation.observed_at == at(minutes)
        )
    )
    return session.get(ObservationQuality, oid)

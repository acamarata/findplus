"""Builders for the people scenarios (specs/people-and-presence.md § 11).

Purpose    : A small synthetic world: Home, School and Grandma's, a person
             "Sam" with a bag, a bike and two pairs of shoes, and a timeline
             builder that ingests every tracker's fixes in time order through
             the real ingest -> geofence -> person hook chain.
Inputs     : The tmp_db-backed `session` fixture (cli/tests/conftest.py).
Outputs    : n/a (test-only builders).
Constraints: test-only; never imported by cli/src. All fixes are synthetic; no
             network, no real account, no real ~/.findplus.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from findplus.db.models import GroupPlaceEvent, Place
from findplus.ingest import ingest_observations, upsert_device
from findplus.people import repo
from findplus.places.repo import create_place
from findplus.providers.base import RawObservation

#: Day 0 midnight UTC; scenarios run "local" time in UTC (pinned_tz("UTC")).
DAY0 = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
HOME = (41.100000, -80.640000)
SCHOOL = (41.127000, -80.640000)  # ~3.0 km north
GRANDMA = (41.100000, -80.580000)  # ~5.0 km east
SAM = {
    "zb": "Sam Bag",
    "zk": "Sam Bike",
    "zr": "Sam Shoes Red",
    "zw": "Sam Shoes White",
}


def at(hour: int, minute: int = 0, day: int = 0) -> datetime:
    return DAY0 + timedelta(days=day, hours=hour, minutes=minute)


def seed_places(session) -> dict[str, Place]:
    out = {}
    for name, (lat, lon), kind in (
        ("Home", HOME, "home"),
        ("School", SCHOOL, "school"),
        ("Grandma's", GRANDMA, "family"),
    ):
        out[name] = create_place(
            session, name=name, latitude_e7=round(lat * 1e7), longitude_e7=round(lon * 1e7),
            radius_meters=150, kind=kind,
        )  # fmt: skip
    session.flush()
    return out


def seed_person(session, name: str = "Sam", trackers: dict[str, str] | None = None, kind="person"):
    trackers = trackers or SAM
    for device_id, label in trackers.items():
        upsert_device(session, device_id, label, provider="test-fake", now=DAY0 - timedelta(days=1))
    group = repo.create_person(session, name=name, kind=kind, member_ids=list(trackers))
    session.flush()
    return group


class Timeline:
    """Collect (time, device, lat, lon) fixes, then ingest them in time order."""

    def __init__(self) -> None:
        self.fixes: list[tuple[datetime, str, float, float, float]] = []

    def stay(self, devices, where, start, end, every=20, acc=30.0):
        t, i = start, 0
        while t <= end:
            for n, d in enumerate(devices):
                jitter = ((i + n) % 3 - 1) * 0.00008  # +-9 m, deterministic
                self.fixes.append((t, d, where[0] + jitter, where[1], acc))
            t, i = t + timedelta(minutes=every), i + 1
        return self

    def walk(self, devices, frm, to, start, end, every=5, acc=30.0):
        steps = max(1, int((end - start).total_seconds() // 60 // every))
        for k in range(1, steps + 1):
            f = k / steps
            lat = frm[0] + (to[0] - frm[0]) * f
            lon = frm[1] + (to[1] - frm[1]) * f
            for d in devices:
                self.fixes.append((start + timedelta(minutes=every * k), d, lat, lon, acc))
        return self

    def add(self, device, where, when, acc=30.0):
        self.fixes.append((when, device, where[0], where[1], acc))
        return self

    def ingest(self, session, lag_minutes: int = 5) -> None:
        by_time: dict[datetime, list] = {}
        for when, d, lat, lon, acc in sorted(self.fixes, key=lambda f: (f[0], f[1])):
            by_time.setdefault(when, []).append(raw(d, lat, lon, when, acc))
        settings = types.SimpleNamespace(
            geofence_default_accuracy_meters=100.0,
            group_window_minutes=30,
            presence_window_minutes=60,
        )
        for when, batch in sorted(by_time.items()):
            ingest_observations(
                session, batch, fetched_at=when + timedelta(minutes=lag_minutes), settings=settings
            )
        session.flush()
        self.fixes = []


def raw(device_id: str, lat: float, lon: float, when: datetime, acc: float = 30.0):
    return RawObservation(
        device_id=device_id,
        device_name=SAM.get(device_id, device_id),
        latitude_e7=round(lat * 1e7),
        longitude_e7=round(lon * 1e7),
        observed_at=when,
        accuracy_meters=acc,
        source="crowdsourced",
        is_own_report=False,
        provider="test-fake",
    )


def person_events(session, group_id: int) -> list[tuple[str, str, datetime]]:
    rows = session.execute(
        select(GroupPlaceEvent.event_type, Place.name, GroupPlaceEvent.observed_at)
        .join(Place, Place.id == GroupPlaceEvent.place_id)
        .where(GroupPlaceEvent.group_id == group_id, GroupPlaceEvent.basis == "person")
        .order_by(GroupPlaceEvent.observed_at)
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def overnight(tl: Timeline, devices, start=None, end=None) -> Timeline:
    """Every tracker at Home from 20:00 the evening before until 07:30."""
    return tl.stay(devices, HOME, start or at(20, 0, day=-1), end or at(7, 30), every=30)

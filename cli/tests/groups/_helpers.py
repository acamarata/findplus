"""Shared seed/builder helpers for the group-events test suite.

Purpose    : One definition of the group/place seed helpers and the raw
             observation builder used across test_events*.py, so splitting
             test_events.py under the 300-line cap (PRI rule 7) does not
             duplicate fixtures.
Inputs     : A SQLAlchemy `session` (from the tmp_db-backed `session` fixture
             in cli/tests/conftest.py).
Outputs    : n/a (test-only builders).
Constraints: test-only; never imported by cli/src.
"""

from __future__ import annotations

from datetime import UTC, datetime

from findplus.db.models import Device, DeviceGroup, Group, LocationObservation, Place, PlaceEvent

T0 = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)


class _Settings:
    group_window_minutes = 30
    presence_window_minutes = 60


def _seed_group(session, quorum: str = "majority") -> tuple[Group, Place]:
    place = Place(
        name="Home",
        latitude_e7=411000000,
        longitude_e7=-806400000,
        radius_meters=100,
        color="#2f80ed",
        enter_confirmations=1,
        exit_confirmations=2,
        created_at=T0,
        updated_at=T0,
    )
    group = Group(
        name="family",
        color="#27ae60",
        quorum=quorum,
        cluster_radius_meters=150,
        stale_after_minutes=90,
        created_at=T0,
    )
    session.add_all([place, group])
    session.flush()
    for device_id in ("a", "b", "c"):
        session.add(
            Device(
                device_id=device_id,
                name=device_id,
                is_tracked=True,
                first_seen_at=T0,
                last_seen_at=T0,
            )
        )
    session.flush()
    for device_id in ("a", "b", "c"):
        session.add(DeviceGroup(device_id=device_id, group_id=group.id))
    session.flush()
    return group, place


def _add_fix(session, device_id: str, observed_at: datetime) -> LocationObservation:
    """A recent LocationObservation, so the member is not stale at `observed_at`."""
    lo = LocationObservation(
        device_id=device_id,
        device_name=device_id,
        latitude_e7=411000000,
        longitude_e7=-806400000,
        observed_at=observed_at,
        first_fetched_at=observed_at,
        last_fetched_at=observed_at,
        times_returned=1,
        source="crowdsourced",
        is_own_report=False,
    )
    session.add(lo)
    session.flush()
    return lo


def _add_place_event(
    session, place: Place, device_id: str, event_type: str, observed_at: datetime
) -> PlaceEvent:
    lo = _add_fix(session, device_id, observed_at)
    pe = PlaceEvent(
        place_id=place.id,
        device_id=device_id,
        event_type=event_type,
        observed_at=observed_at,
        fetched_at=observed_at,
        observation_id=lo.id,
        confidence="high",
        distance_meters=10.0,
        accuracy_meters=10.0,
        notified_at=None,
    )
    session.add(pe)
    session.flush()
    return pe


def _raw_obs(device_id: str, observed_at: datetime):
    from findplus.findhub.types import RawObservation

    return RawObservation(
        device_id=device_id,
        device_name=device_id,
        latitude_e7=411000000,
        longitude_e7=-806400000,
        observed_at=observed_at,
        accuracy_meters=30.0,
        source="crowdsourced",
        is_own_report=False,
    )

"""Shared seed/builder helpers for the alerts dispatch test suite.

Purpose    : One definition of the DeviceEvent/GroupEvent builders and DB
             seed helpers used across test_dispatch*.py, so splitting those
             modules under the 300-line cap (PRI rule 7) does not duplicate
             fixtures or drift them apart.
Inputs     : A SQLAlchemy `session` (from the tmp_db-backed `session` fixture
             in cli/tests/conftest.py).
Outputs    : n/a (test-only builders).
Constraints: test-only; never imported by cli/src.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime

from findplus.alerts.dispatch import DeviceEvent, GroupEvent
from findplus.db.models import (
    Device,
    Group,
    GroupPlaceEvent,
    LocationObservation,
    Place,
    PlaceEvent,
)
from findplus.db.models_alerts import AlertRule

NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)


def _seed_place_and_device(s, place_id=1, device_id="dev1", label=None) -> None:
    if s.get(Place, place_id) is None:
        s.add(
            Place(
                id=place_id,
                name="Home",
                latitude_e7=0,
                longitude_e7=0,
                radius_meters=100,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    if s.get(Device, device_id) is None:
        s.add(
            Device(
                device_id=device_id,
                name="Tag",
                label=label,
                is_tracked=True,
                provider="google-find-hub",
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
    s.flush()


def _seed_group(s, group_id=1, name="Family") -> None:
    if s.get(Group, group_id) is None:
        s.add(Group(id=group_id, name=name, created_at=NOW))
        s.flush()


def _device_event(**overrides) -> DeviceEvent:
    base = dict(
        place_event_id=1,
        place_id=1,
        place_name="Home",
        device_id="dev1",
        device_name="Tag",
        event_type="ENTER",
        observed_at=NOW,
        fetched_at=NOW,
        confidence="high",
        group_ids=[],
    )
    base.update(overrides)
    return DeviceEvent(**base)


def _telegram_configured(none: bool = False):
    """`none=True` mimics telegram being removed/unconfigured mid-backoff
    (test_dispatch_retry.py R5): channels_cfg.telegram is None, so
    dispatch_send._send() returns None and _status_for classifies "skipped"."""
    return types.SimpleNamespace(
        telegram=None if none else types.SimpleNamespace(bot_token="t", chat_ids=("1",)),
        webhook=None,
    )


def _seed_place(s, place_id, name) -> None:
    if s.get(Place, place_id) is None:
        s.add(
            Place(
                id=place_id,
                name=name,
                latitude_e7=0,
                longitude_e7=0,
                radius_meters=100,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        s.flush()


def _seed_pending_place_event(s, place_id, observed_at, device_id="dev1") -> None:
    """A real place_events row (+ its FK'd location_observations row), notified_at NULL."""
    obs = LocationObservation(
        device_id=device_id,
        device_name="Tag",
        latitude_e7=0,
        longitude_e7=0,
        observed_at=observed_at,
        first_fetched_at=observed_at,
        last_fetched_at=observed_at,
        times_returned=1,
    )
    s.add(obs)
    s.flush()
    s.add(
        PlaceEvent(
            place_id=place_id,
            device_id=device_id,
            event_type="ENTER",
            observed_at=observed_at,
            fetched_at=observed_at,
            observation_id=obs.id,
            confidence="high",
            distance_meters=10.0,
            notified_at=None,
        )
    )
    s.commit()


def _seed_group_place_event(s, group_id, place_id, observed_at) -> int:
    """A real group_place_events row. Returns its id for GroupEvent(group_place_event_id=...)."""
    row = GroupPlaceEvent(
        group_id=group_id,
        place_id=place_id,
        event_type="ENTER",
        observed_at=observed_at,
        member_event_ids="[]",
        members_crossed=2,
        members_considered=2,
        members_stale=0,
        confidence="high",
        notified_at=None,
    )
    s.add(row)
    s.commit()
    return row.id


def _group_event(**overrides) -> GroupEvent:
    base = dict(
        group_place_event_id=1,
        group_id=1,
        group_name="Family",
        place_id=1,
        place_name="Home",
        event_type="ENTER",
        observed_at=NOW,
        confidence="high",
        note="",
        members_crossed=2,
        members_considered=2,
        members_stale=0,
    )
    base.update(overrides)
    return GroupEvent(**base)


def _send_ok():
    return types.SimpleNamespace(success=True, status_code=200, error=None)


def _rule(**overrides) -> AlertRule:
    base = dict(
        name="any-place",
        place_id=None,
        device_id="dev1",
        on_enter=True,
        on_exit=True,
        channels="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    base.update(overrides)
    return AlertRule(**base)

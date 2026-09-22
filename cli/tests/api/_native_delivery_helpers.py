"""Shared seed helpers for the native-deliveries route tests, split out of
test_routes_alerts_deliveries_native.py (E13 stage 2, size cap).

Purpose    : Build the rule/place/device/event/delivery rows both
             test_routes_alerts_deliveries_native.py and
             test_routes_alerts_deliveries_native_perf.py need. Each file
             keeps its own small `client` fixture (importing a fixture used
             as a same-named test parameter trips ruff's F811).
Inputs     : None (each helper takes only the ids it needs).
Outputs    : ids of the rows created, for the caller to build deliveries on.
Constraints: Every row uses the same fixed `NOW` timestamp so tests can
             assert exact rendered text/body without a clock dependency.
"""

from __future__ import annotations

import datetime

from findplus.db.models import (
    Device,
    Group,
    GroupPlaceEvent,
    LocationObservation,
    Place,
    PlaceEvent,
)
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.db.session import session_scope

NOW = datetime.datetime(2026, 9, 20, 12, 0, 0, tzinfo=datetime.UTC)


def _seed_place_event(s) -> int:
    """One observed ENTER PlaceEvent for `dev1` at place_id=1; returns its id."""
    obs = LocationObservation(
        device_id="dev1",
        device_name="Tag",
        latitude_e7=0,
        longitude_e7=0,
        observed_at=NOW,
        first_fetched_at=NOW,
        last_fetched_at=NOW,
        times_returned=1,
    )
    s.add(obs)
    s.flush()
    event = PlaceEvent(
        place_id=1,
        device_id="dev1",
        event_type="ENTER",
        observed_at=NOW,
        fetched_at=NOW,
        observation_id=obs.id,
        confidence="high",
        distance_meters=10.0,
    )
    s.add(event)
    s.flush()
    return event.id


def _seed(place_event: bool = True) -> tuple[int, int]:
    """One rule plus (optionally) one place_event; returns (rule_id, place_event_id)."""
    with session_scope() as s:
        s.add(
            Place(
                id=1,
                name="Home",
                latitude_e7=0,
                longitude_e7=0,
                radius_meters=100,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        s.add(
            Device(
                device_id="dev1",
                name="Tag",
                is_tracked=True,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
        s.flush()
        rule = AlertRule(
            name="native rule",
            place_id=1,
            device_id="dev1",
            on_enter=True,
            on_exit=True,
            channels="native",
            cooldown_minutes=30,
            enabled=True,
            also_notify_members=False,
            created_at=NOW,
        )
        s.add(rule)
        s.flush()
        event_id = _seed_place_event(s) if place_event else 0
        s.commit()
        return rule.id, event_id


def _add_delivery(
    rule_id: int, event_id: int, channel: str, status: str = "queued", event_kind: str = "device"
) -> int:
    with session_scope() as s:
        row = AlertDelivery(
            rule_id=rule_id,
            event_kind=event_kind,
            event_id=event_id,
            channel=channel,
            sent_at=NOW,
            status=status,
        )
        s.add(row)
        s.commit()
        return row.id


def _seed_group() -> int:
    """A group + one group_place_event at place_id=1 (from `_seed()`); returns its id."""
    with session_scope() as s:
        s.add(
            Group(
                id=1,
                name="Family",
                color="#27ae60",
                icon="lucide:users",
                quorum="majority",
                cluster_radius_meters=150,
                stale_after_minutes=90,
                created_at=NOW,
            )
        )
        s.flush()
        row = GroupPlaceEvent(
            group_id=1,
            place_id=1,
            event_type="ENTER",
            observed_at=NOW,
            member_event_ids="[]",
            members_crossed=2,
            members_considered=3,
            members_stale=1,
            confidence="medium",
            notified_at=None,
        )
        s.add(row)
        s.commit()
        return row.id

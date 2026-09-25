"""End to end: a real device crossing drives a group alert rule.

Purpose    : Prove the "anyone leaves Home" group scenario -- the same real
             ingest -> geofence -> group-quorum -> dispatch chain as
             test_geofence_alerts_e2e.py, but with a quorum='any' group rule
             instead of a device rule, and a second member who never reports
             at all. Split into its own file for the PRI 300-line file cap.
Inputs     : A FakeProvider feeding one fix per poll_device() call at a Home
             place ((0,0), radius 100m); dev2 gets no fixture fix at all, so
             it is stale by construction. The only other mock is the outbound
             HTTP call in findplus.alerts.channels.telegram.send. Shared
             builders live in geofence_alerts_helpers.py.
Outputs    : n/a (pytest assertions).
Constraints: Never touches the network or the real ~/.findplus (conftest.py's
             autouse fixtures already enforce this).
"""

from __future__ import annotations

from datetime import UTC, datetime

from findplus.alerts.channels_field import format_channels
from findplus.config import Settings
from findplus.db.models import Device, DeviceGroup, Group
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.ingest import upsert_device
from tests.geofence_alerts_helpers import (
    OUTSIDE_LAT,
    ZONE,
    assert_message,
    feed,
    run_dispatch,
    seed_home,
)


def _seed_group_and_rule(session, base: datetime) -> None:
    """Home + Family group (dev1, dev2 -- dev2 never gets a fix, so it is
    always stale) + a quorum='any' "anyone leaves Home" group rule."""
    seed_home(session, base)
    upsert_device(session, "dev1", "Tag1", provider="test-fake", now=base)
    session.add(
        Device(
            device_id="dev2",
            name="Tag2",
            is_tracked=False,
            provider="test-fake",
            first_seen_at=base,
            last_seen_at=base,
        )
    )
    session.add(Group(id=1, name="Family", quorum="any", created_at=base))
    session.flush()  # Device(dev2)/Group(1) rows must exist before device_group's FKs
    session.add_all(
        [DeviceGroup(device_id="dev1", group_id=1), DeviceGroup(device_id="dev2", group_id=1)]
    )
    session.add(
        AlertRule(
            name="anyone-leaves",
            place_id=1,
            group_id=1,
            device_id=None,
            on_enter=False,
            on_exit=True,
            channels=format_channels(["telegram"]),
            cooldown_minutes=30,
            enabled=True,
            also_notify_members=False,
            created_at=base,
        )
    )
    session.commit()


def test_group_rule_fires_when_a_member_leaves_home(session, register_provider, pinned_tz) -> None:
    """A quorum='any' group rule fires when one member leaves; a member with no
    fix ever (dev2) is stale and never counted as having crossed too -- the
    note says "1 of 1 tags left", never "2 of 2" (PRESENCE_STALE honesty rule:
    a tracker with no recent fix is not at home and not left behind)."""
    pinned_tz(ZONE)
    base = datetime.now(UTC)
    _seed_group_and_rule(session, base)
    ingest_settings = Settings(alerts_enabled=False)

    # inside 20min ago -> outside 15min ago -> outside 10min ago (EXIT).
    for minutes_ago, lat in ((20, 0.0), (15, OUTSIDE_LAT), (10, OUTSIDE_LAT)):
        feed(
            register_provider,
            "dev1",
            "Tag1",
            base=base,
            minutes_ago=minutes_ago,
            lat=lat,
            accuracy=20,
            settings=ingest_settings,
        )

    tg_mock = run_dispatch(session, now=base)
    assert tg_mock.call_count == 1
    assert_message(
        tg_mock.call_args[0][0],
        "Family",
        "left",
        base=base,
        when_minutes_ago=10,
        confidence="medium",
        note="1 of 1 tags left Home; 1 tag has no recent fix.",
    )
    assert session.query(AlertDelivery).filter_by(event_kind="device").count() == 0

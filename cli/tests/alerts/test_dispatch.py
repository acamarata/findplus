"""alerts/dispatch.py: delivery, failure, dedup, disabled, pending-load, concurrency.

Split (PRI rule 7, <=300 lines/file): group-vs-device suppression lives in
test_dispatch_groups.py, render_message/as_utc formatting in
test_dispatch_messages.py. Shared seed/builder helpers moved to _helpers.py;
shared fixtures (settings_enabled, rule_row) moved to conftest.py.
"""

from __future__ import annotations

import types
from datetime import timedelta
from unittest.mock import patch

from findplus.alerts.dispatch import load_pending_events, process
from findplus.db.models_alerts import AlertDelivery

from ._helpers import (
    NOW,
    _device_event,
    _seed_place_and_device,
    _telegram_configured,
)


def test_flapping_200_events(rule_row, session, settings_enabled) -> None:
    events = [
        _device_event(place_event_id=i, event_type="ENTER" if i % 2 == 0 else "EXIT")
        for i in range(1, 201)
    ]
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send") as send_mock,
    ):
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        process(events, session, settings_enabled, now=NOW)
    sent = session.query(AlertDelivery).filter_by(status="sent").all()
    assert len(sent) == 1


def test_failure_recorded(rule_row, session, settings_enabled) -> None:
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch(
            "findplus.alerts.channels.telegram.send",
            side_effect=RuntimeError("telegram: bot was blocked or kicked (403)"),
        ),
    ):
        process([_device_event()], session, settings_enabled, now=NOW)
    row = session.query(AlertDelivery).one()
    assert row.status == "failed"


def test_alerts_disabled(rule_row, session) -> None:
    settings = types.SimpleNamespace(alerts_enabled=False)
    process([_device_event()], session, settings, now=NOW)
    assert session.query(AlertDelivery).count() == 0


def test_dedup(rule_row, session, settings_enabled) -> None:
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send") as send_mock,
    ):
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        process([_device_event()], session, settings_enabled, now=NOW)
        process([_device_event()], session, settings_enabled, now=NOW)
    assert session.query(AlertDelivery).count() == 1


def test_load_pending_events_marks_notified(session, settings_enabled) -> None:
    from findplus.db.models import LocationObservation, PlaceEvent
    from findplus.db.models_alerts import AlertRule as _AlertRule  # noqa: F401 (documents schema)
    from findplus.groups.repo import create_group

    _seed_place_and_device(session)
    create_group(session, name="Family", member_ids=["dev1"])
    session.add(
        LocationObservation(
            id=1,
            device_id="dev1",
            device_name="Tag",
            latitude_e7=0,
            longitude_e7=0,
            observed_at=NOW,
            first_fetched_at=NOW,
            last_fetched_at=NOW,
            times_returned=1,
        )
    )
    session.add(
        PlaceEvent(
            place_id=1,
            device_id="dev1",
            event_type="ENTER",
            observed_at=NOW,
            fetched_at=NOW,
            observation_id=1,
            confidence="high",
            distance_meters=10.0,
            notified_at=None,
        )
    )
    session.commit()

    events = load_pending_events(session)
    assert len(events) == 1
    ev = events[0]
    assert ev.place_name == "Home"
    assert ev.device_name == "Tag"
    assert ev.group_ids == [1]

    empty_channels = types.SimpleNamespace(telegram=None, webhook=None)
    with patch("findplus.alerts.store.load_alerts", return_value=empty_channels):
        process(events, session, settings_enabled, now=NOW)

    session.expire_all()
    row = session.query(PlaceEvent).one()
    assert row.notified_at is not None


def test_end_to_end_from_db_rows_sends(rule_row, session, settings_enabled) -> None:
    """The real load -> process path: raw SQL hands back str timestamps, not datetimes."""
    from findplus.db.models import LocationObservation, PlaceEvent

    session.add(
        LocationObservation(
            id=1,
            device_id="dev1",
            device_name="Tag",
            latitude_e7=0,
            longitude_e7=0,
            observed_at=NOW,
            first_fetched_at=NOW,
            last_fetched_at=NOW,
            times_returned=1,
        )
    )
    session.add(
        PlaceEvent(
            place_id=1,
            device_id="dev1",
            event_type="ENTER",
            observed_at=NOW,
            fetched_at=NOW + timedelta(minutes=4),
            observation_id=1,
            confidence="high",
            distance_meters=10.0,
            notified_at=None,
        )
    )
    session.commit()

    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send") as send_mock,
    ):
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        process(load_pending_events(session), session, settings_enabled, now=NOW)

    row = session.query(AlertDelivery).one()
    assert row.status == "sent", row.error
    assert "4 min late" in send_mock.call_args[0][0]


class _RacySession:
    """Delegates to the real session, but the dedup SELECT always misses.

    Used by test_concurrent_duplicate_delivery_is_rolled_back to simulate a
    second poller's insert racing the UNIQUE constraint.
    """

    def __init__(self, real) -> None:
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def query(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return None


def test_concurrent_duplicate_delivery_is_rolled_back(rule_row, session) -> None:
    """A second poller's insert loses to the UNIQUE constraint instead of raising."""
    from findplus.alerts.dispatch import Rule, _deliver_one

    rule = Rule(
        id=rule_row.id,
        name=rule_row.name,
        place_id=1,
        group_id=None,
        device_id="dev1",
        on_enter=True,
        on_exit=True,
        channels=["telegram"],
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
    )
    session.add(
        AlertDelivery(
            rule_id=rule.id,
            event_kind="device",
            event_id=1,
            channel="telegram",
            sent_at=NOW,
            status="sent",
        )
    )
    session.commit()

    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send") as send_mock,
    ):
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        result = _deliver_one(
            _RacySession(session), rule, "telegram", _device_event(), _telegram_configured(), NOW
        )

    assert result is None
    assert session.query(AlertDelivery).count() == 1


def test_unconfigured_channel_records_a_skipped_delivery(rule_row, session, settings_enabled):
    """A rule whose channel has no credentials used to swallow the event (E1 CR-C).

    `_send` returned None, `_deliver_one` bailed before writing a row, and
    `process` stamped notified_at anyway — so nothing reached
    GET /api/alerts/deliveries and the event could never fire again once the
    channel was configured. `status="skipped"` was CHECK-legal but never written.
    """
    no_channels = types.SimpleNamespace(telegram=None, webhook=None)
    with patch("findplus.alerts.store.load_alerts", return_value=no_channels):
        process([_device_event()], session, settings_enabled, now=NOW)

    row = session.query(AlertDelivery).one()
    assert row.status == "skipped"
    assert "telegram" in row.error


def test_a_skipped_delivery_does_not_start_a_cooldown(rule_row, session, settings_enabled):
    """Delivery.status defaults to "sent", so the skipped row must carry its own.

    process() appends each returned Delivery to the in-memory cooldown list. If the
    status did not travel with it, the next same-key event in the same run would be
    suppressed by a delivery that never actually went out.
    """
    no_channels = types.SimpleNamespace(telegram=None, webhook=None)
    events = [
        _device_event(place_event_id=1, event_type="ENTER"),
        _device_event(place_event_id=2, event_type="EXIT"),
    ]
    with patch("findplus.alerts.store.load_alerts", return_value=no_channels):
        process(events, session, settings_enabled, now=NOW)

    rows = session.query(AlertDelivery).all()
    assert [r.status for r in rows] == ["skipped", "skipped"]

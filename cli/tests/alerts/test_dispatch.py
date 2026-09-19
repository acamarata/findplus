"""alerts/dispatch.py: flapping, suppression, failure, lag, disabled, dedup, pending-load."""

from __future__ import annotations

import types
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from findplus.alerts.dispatch import DeviceEvent, load_pending_events, process
from findplus.db.models import Device, Group, Place
from findplus.db.models_alerts import AlertDelivery, AlertRule

NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def settings_enabled():
    return types.SimpleNamespace(alerts_enabled=True)


def _seed_place_and_device(s, place_id=1, device_id="dev1") -> None:
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


@pytest.fixture
def rule_row(tmp_db, session):
    _seed_place_and_device(session)
    rule = AlertRule(
        name="r1",
        place_id=1,
        device_id="dev1",
        on_enter=True,
        on_exit=True,
        channel="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    session.add(rule)
    session.commit()
    return rule


def _telegram_configured():
    return types.SimpleNamespace(
        telegram=types.SimpleNamespace(bot_token="t", chat_id="1"), webhook=None
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


def test_group_rule_suppresses_device_rule(session, settings_enabled) -> None:
    _seed_place_and_device(session)
    _seed_group(session)
    device_rule = AlertRule(
        name="device-rule",
        place_id=1,
        device_id="dev1",
        channel="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    group_rule = AlertRule(
        name="group-rule",
        place_id=1,
        group_id=1,
        channel="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    session.add_all([device_rule, group_rule])
    session.commit()

    event = _device_event(group_ids=[1])
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send") as send_mock,
    ):
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        process([event], session, settings_enabled, now=NOW)
        assert send_mock.call_count == 0


def test_group_rule_also_notify_not_suppressed(session, settings_enabled) -> None:
    _seed_place_and_device(session)
    _seed_group(session)
    device_rule = AlertRule(
        name="device-rule",
        place_id=1,
        device_id="dev1",
        channel="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    group_rule = AlertRule(
        name="group-rule",
        place_id=1,
        group_id=1,
        channel="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=True,
        created_at=NOW,
    )
    session.add_all([device_rule, group_rule])
    session.commit()

    event = _device_event(group_ids=[1])
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send") as send_mock,
    ):
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        process([event], session, settings_enabled, now=NOW)
    # match() only ever matches a DeviceEvent against device-targeted rules
    # (engines.md), so the group rule itself never fires here -- only that it
    # no longer SUPPRESSES the device rule, which does fire.
    assert send_mock.call_count == 1


def test_failure_recorded(rule_row, session, settings_enabled) -> None:
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", side_effect=RuntimeError("boom")),
    ):
        process([_device_event()], session, settings_enabled, now=NOW)
    row = session.query(AlertDelivery).one()
    assert row.status == "failed"


def test_lag_in_message() -> None:
    from findplus.alerts.dispatch import render_message

    event = _device_event(fetched_at=NOW + timedelta(minutes=5))
    msg = render_message(event, NOW)
    assert "5 min late" in msg


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

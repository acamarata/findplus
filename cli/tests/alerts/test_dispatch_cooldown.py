"""alerts/dispatch.py: cooldown scoped per place, and GroupEvent end-to-end dispatch.

Purpose : Cover the E6 CR-C ruling (engines.md "Rulings 2026-09-19" / "Cooldown
          key") -- in_cooldown() must key on (rule.id, place_id, subject), not
          just (rule.id, event_kind), so a place_id=None rule cools down per
          place instead of across every place. Split out of test_dispatch.py
          (PRI hard rule: <=300 lines/file) the same way dispatch_core.py was
          split out of dispatch.py.
Inputs  : Real DB rows (place_events / group_place_events / alert_rules) via
          the `session` fixture -- no mocked ORM.
Outputs : n/a (pytest assertions).
Constraints: Never touches the network or the real ~/.findplus (conftest.py
          fixtures already enforce this).
"""

from __future__ import annotations

import types
from datetime import timedelta
from unittest.mock import patch

import pytest

from findplus.alerts.dispatch import GroupEvent, load_pending_events, process
from findplus.db.models import GroupPlaceEvent, LocationObservation, Place, PlaceEvent
from findplus.db.models_alerts import AlertDelivery, AlertRule

from .test_dispatch import NOW, _seed_group, _seed_place_and_device, _telegram_configured


@pytest.fixture
def settings_enabled():
    return types.SimpleNamespace(alerts_enabled=True)


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
        channel="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    base.update(overrides)
    return AlertRule(**base)


def test_cooldown_scoped_per_place_not_across_places(session, settings_enabled) -> None:
    """A place_id=None rule cools down per place: Home then Work 5 min apart both send."""
    _seed_place_and_device(session)
    _seed_place(session, place_id=2, name="Work")
    session.add(_rule())
    session.commit()

    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()),
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)

    later = NOW + timedelta(minutes=5)
    _seed_pending_place_event(session, place_id=2, observed_at=later)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()),
    ):
        process(load_pending_events(session), session, settings_enabled, now=later)

    assert session.query(AlertDelivery).filter_by(status="sent").count() == 2


def test_cooldown_same_place_twice_suppressed(session, settings_enabled) -> None:
    """Two crossings of the SAME place inside the cooldown window: second is suppressed."""
    _seed_place_and_device(session)
    session.add(_rule())
    session.commit()

    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()),
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)

    later = NOW + timedelta(minutes=5)
    _seed_pending_place_event(session, place_id=1, observed_at=later)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()) as send_mock,
    ):
        process(load_pending_events(session), session, settings_enabled, now=later)
        assert send_mock.call_count == 0  # the second crossing never reaches the channel

    assert session.query(AlertDelivery).filter_by(status="sent").count() == 1


def test_group_cooldown_scoped_per_place(session, settings_enabled) -> None:
    """A group rule's cooldown is keyed per (rule, place) too, same as a device rule."""
    _seed_place_and_device(session)
    _seed_place(session, place_id=2, name="Work")
    _seed_group(session)
    session.add(_rule(name="group-any-place", device_id=None, group_id=1))
    session.commit()

    home_id = _seed_group_place_event(session, group_id=1, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()),
    ):
        process(
            [_group_event(group_place_event_id=home_id, place_id=1, place_name="Home")],
            session,
            settings_enabled,
            now=NOW,
        )

    later = NOW + timedelta(minutes=5)
    work_id = _seed_group_place_event(session, group_id=1, place_id=2, observed_at=later)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()),
    ):
        process(
            [_group_event(group_place_event_id=work_id, place_id=2, place_name="Work")],
            session,
            settings_enabled,
            now=later,
        )

    assert session.query(AlertDelivery).filter_by(status="sent", event_kind="group").count() == 2


def test_group_event_end_to_end_dispatch(session, settings_enabled) -> None:
    """A real group_place_events row + a group rule: process() sends and the note lands."""
    _seed_place_and_device(session)
    _seed_group(session)
    session.add(_rule(name="group-rule", device_id=None, place_id=1, group_id=1))
    session.commit()

    gpe_id = _seed_group_place_event(session, group_id=1, place_id=1, observed_at=NOW)
    event = _group_event(group_place_event_id=gpe_id, note="2 of 2 members crossed")

    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()) as send_mock,
    ):
        process([event], session, settings_enabled, now=NOW)

    row = session.query(AlertDelivery).filter_by(event_kind="group").one()
    assert row.status == "sent", row.error
    sent_text = send_mock.call_args[0][0]
    assert "2 of 2 members crossed" in sent_text


def test_group_event_note_states_who_actually_crossed(session, settings_enabled) -> None:
    """load_pending_events must rebuild the note group_place_events cannot store.

    Without it every group alert reads "the group arrived", which is exactly the
    overstatement PROMPT.md §6 forbids when only a quorum crossed and a member
    has no recent fix.
    """
    _seed_place_and_device(session)
    _seed_group(session)
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
    session.add(row)
    session.commit()

    events = [e for e in load_pending_events(session) if isinstance(e, GroupEvent)]
    assert len(events) == 1
    assert events[0].note == "2 of 3 tags entered Home; 1 tag has no recent fix."


def test_group_event_note_reaches_the_sent_message(session, settings_enabled) -> None:
    _seed_place_and_device(session)
    _seed_group(session)
    session.add(_rule(name="group-rule", device_id=None, place_id=1, group_id=1))
    _seed_group_place_event(session, group_id=1, place_id=1, observed_at=NOW)
    session.commit()

    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()) as send_mock,
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)

    sent = [c[0][0] for c in send_mock.call_args_list]
    assert any("2 of 2 tags entered Home." in text for text in sent), sent

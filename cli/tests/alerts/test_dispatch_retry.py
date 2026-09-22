"""alerts/retry.py: transient-failure classification and scheduling.

Purpose : Cover the owner's retry ladder end to end with a controlled clock
          (explicit `now` on every call, never wall time) and a fake channel
          send (patched telegram.send) -- no network, per PRI rule 3.
Inputs   : rule_row/session/settings_enabled fixtures from conftest.py; real
           place_events rows (retry.py reloads events from the DB by id, so a
           synthetic DeviceEvent with no backing row cannot be retried).

The drain-bounding, supersession, unconfigured-channel and same-text-on-retry
tests moved to test_dispatch_retry_drain.py (E13 stage 2, size cap); the fake
result builders moved to _retry_helpers.py.
"""

from __future__ import annotations

import types
from datetime import timedelta
from unittest.mock import patch

from findplus.alerts.dispatch import load_pending_events, process
from findplus.alerts.retry import process_retries
from findplus.db.models import PlaceEvent
from findplus.db.models_alerts import AlertDelivery, AlertRule

from ._helpers import NOW, _seed_pending_place_event, _telegram_configured
from ._retry_helpers import _bad_request, _rate_limited, _seed_and_process, _sent, _timeout


def test_transient_failure_schedules_a_one_minute_retry(rule_row, session, settings_enabled):
    _seed_and_process(rule_row, session, settings_enabled, _timeout())
    row = session.query(AlertDelivery).one()
    assert row.status == "retrying"
    assert row.attempts == 1
    assert row.next_attempt_at == NOW + timedelta(minutes=1)


def test_transient_failure_then_success_on_retry(rule_row, session, settings_enabled):
    _seed_and_process(rule_row, session, settings_enabled, _timeout())
    later = NOW + timedelta(minutes=1)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_sent()),
    ):
        processed = process_retries(session, now=later)

    session.expire_all()
    row = session.query(AlertDelivery).one()
    assert processed == 1
    assert row.status == "sent"
    assert row.attempts == 2
    assert row.next_attempt_at is None


def test_transient_failure_exhausts_after_four_attempts(rule_row, session, settings_enabled):
    _seed_and_process(rule_row, session, settings_enabled, _timeout())
    offsets = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30))
    for offset in offsets:
        due = NOW + offset
        with (
            patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
            patch("findplus.alerts.channels.telegram.send", return_value=_timeout()),
        ):
            process_retries(session, now=due)
        session.expire_all()

    row = session.query(AlertDelivery).one()
    assert row.status == "failed"
    assert row.attempts == 4
    assert row.next_attempt_at is None


def test_permanent_4xx_is_never_retried(rule_row, session, settings_enabled):
    _seed_and_process(rule_row, session, settings_enabled, _bad_request())
    row = session.query(AlertDelivery).one()
    assert row.status == "failed"
    assert row.attempts == 1
    assert row.next_attempt_at is None
    # Nothing due: process_retries must find no row to touch.
    assert process_retries(session, now=NOW + timedelta(hours=1)) == 0


def test_429_retry_after_header_pushes_past_the_ladder_value(rule_row, session, settings_enabled):
    _seed_and_process(rule_row, session, settings_enabled, _rate_limited(retry_after=600))
    row = session.query(AlertDelivery).one()
    assert row.status == "retrying"
    # 600 s (10 min) beats the 1-minute ladder value and is still < the 30-min cap.
    assert row.next_attempt_at == NOW + timedelta(seconds=600)


def test_retry_after_never_exceeds_the_thirty_minute_cap(rule_row, session, settings_enabled):
    _seed_and_process(rule_row, session, settings_enabled, _rate_limited(retry_after=7200))
    row = session.query(AlertDelivery).one()
    assert row.next_attempt_at == NOW + timedelta(minutes=30)


def test_retry_resumes_from_db_state_alone(rule_row, session):
    """Simulates a daemon restart: build the row directly, no process() call first."""
    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    event_id = session.query(PlaceEvent).order_by(PlaceEvent.id.desc()).first().id
    session.add(
        AlertDelivery(
            rule_id=rule_row.id,
            event_kind="device",
            event_id=event_id,
            channel="telegram",
            sent_at=NOW,
            status="retrying",
            error="timeout",
            attempts=1,
            next_attempt_at=NOW + timedelta(minutes=1),
        )
    )
    session.commit()

    later = NOW + timedelta(minutes=1)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_sent()),
    ):
        processed = process_retries(session, now=later)

    assert processed == 1
    row = session.query(AlertDelivery).one()
    assert row.status == "sent"


def test_native_channel_is_never_scheduled_for_retry(session):
    from ._helpers import _seed_place_and_device

    _seed_place_and_device(session)
    session.add(
        AlertRule(
            name="native-rule",
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
    )
    session.commit()
    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    settings = types.SimpleNamespace(alerts_enabled=True)
    process(load_pending_events(session), session, settings, now=NOW)

    row = session.query(AlertDelivery).one()
    assert row.status == "queued"
    assert row.attempts == 1
    assert row.next_attempt_at is None
    assert process_retries(session, now=NOW + timedelta(hours=1)) == 0


def test_successful_retry_does_not_duplicate_the_row(rule_row, session, settings_enabled):
    _seed_and_process(rule_row, session, settings_enabled, _timeout())
    later = NOW + timedelta(minutes=1)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_sent()),
    ):
        process_retries(session, now=later)
    assert session.query(AlertDelivery).count() == 1


def test_retrying_status_does_not_start_a_cooldown(rule_row, session, settings_enabled):
    """A rule whose only delivery is 'retrying' must still fire on the next
    crossing -- only a 'sent' delivery may start a cooldown. The 'sent'
    control below is what makes this test able to fail: without it, a
    permanently-False in_cooldown() (e.g. a broken `d.status == "sent"`
    filter) would pass this test just as easily as a correct one (R6)."""
    from findplus.alerts.dispatch import Rule
    from findplus.alerts.dispatch_core import Delivery, in_cooldown

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
    from ._helpers import _device_event

    retrying = Delivery(
        rule_id=rule.id,
        event_kind="device",
        event_id=1,
        sent_at=NOW,
        channel="telegram",
        status="retrying",
        place_id=1,
    )
    sent = Delivery(
        rule_id=rule.id,
        event_kind="device",
        event_id=1,
        sent_at=NOW,
        channel="telegram",
        status="sent",
        place_id=1,
    )
    # Control: an otherwise-identical "sent" delivery DOES start the cooldown.
    assert in_cooldown(rule, "telegram", _device_event(), [sent], NOW) is True
    assert in_cooldown(rule, "telegram", _device_event(), [retrying], NOW) is False

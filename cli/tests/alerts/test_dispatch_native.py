"""dispatch.py's native channel: a queued row instead of a send, keyed per channel.

Purpose    : Pin that a "native" channel writes a queue entry the desktop app
             drains, never calls a sender, and cools down independently of the
             other channels on the same rule (specs/notifications.md § 2, § 4).
Constraints: Split out of test_dispatch.py, which was at the 300-line cap.
"""

from __future__ import annotations

import types
from datetime import timedelta
from unittest.mock import patch

from findplus.alerts import dispatch
from findplus.db.models_alerts import AlertDelivery, AlertRule

from ._helpers import (
    NOW,
    _device_event,
    _seed_pending_place_event,
    _seed_place_and_device,
    _telegram_configured,
)


def _multi_channel_rule(session, channels: str, cooldown: int = 30):

    _seed_place_and_device(session)
    rule = AlertRule(
        name="multi",
        place_id=1,
        device_id="dev1",
        on_enter=True,
        on_exit=True,
        channels=channels,
        cooldown_minutes=cooldown,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    session.add(rule)
    session.commit()
    return rule


def _deliveries(session):

    return session.query(AlertDelivery).order_by(AlertDelivery.id).all()


def test_a_native_rule_queues_a_row_and_sends_nothing(session, settings_enabled) -> None:
    _multi_channel_rule(session, "native")
    _seed_pending_place_event(session, 1, NOW)
    session.commit()
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send") as send_mock,
    ):
        dispatch.process(dispatch.load_pending_events(session), session, settings_enabled, now=NOW)
    rows = _deliveries(session)
    assert [(r.channel, r.status, r.error) for r in rows] == [("native", "queued", None)]
    assert send_mock.call_count == 0
    assert rows[0].delivered_at is None


def test_one_event_under_two_channels_makes_one_row_each(session, settings_enabled) -> None:
    _multi_channel_rule(session, "native,telegram")
    _seed_pending_place_event(session, 1, NOW)
    session.commit()
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send") as send_mock,
    ):
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        dispatch.process(dispatch.load_pending_events(session), session, settings_enabled, now=NOW)
    rows = _deliveries(session)
    assert {(r.channel, r.status) for r in rows} == {("native", "queued"), ("telegram", "sent")}
    assert send_mock.call_count == 1


def test_native_keeps_queueing_while_telegram_is_cooling_down(session, settings_enabled) -> None:
    """in_cooldown only counts status == "sent", and it now keys per channel.

    A queued native row never starts a cooldown of its own, and a sent telegram
    row must not suppress the native alert at the same rule and place.
    """
    _multi_channel_rule(session, "native,telegram", cooldown=30)
    _seed_pending_place_event(session, 1, NOW)
    session.commit()
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send") as send_mock,
    ):
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        dispatch.process(dispatch.load_pending_events(session), session, settings_enabled, now=NOW)
        _seed_pending_place_event(session, 1, NOW + timedelta(minutes=5))
        session.commit()
        later = NOW + timedelta(minutes=5)
        dispatch.process(
            dispatch.load_pending_events(session), session, settings_enabled, now=later
        )
    rows = _deliveries(session)
    assert [r.channel for r in rows if r.status == "queued"] == ["native", "native"]
    assert send_mock.call_count == 1  # telegram stayed inside its own cooldown


def test_in_cooldown_is_keyed_per_channel(session) -> None:
    from findplus.alerts.dispatch_core import Delivery, Rule, in_cooldown

    rule = Rule(
        id=1,
        name="r",
        place_id=1,
        group_id=None,
        device_id="dev1",
        on_enter=True,
        on_exit=True,
        channels=["native", "telegram"],
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
    )
    sent_telegram = Delivery(
        rule_id=1,
        event_kind="device",
        event_id=1,
        sent_at=NOW,
        channel="telegram",
        status="sent",
        place_id=1,
    )
    event = _device_event()
    assert in_cooldown(rule, "telegram", event, [sent_telegram], NOW)
    assert not in_cooldown(rule, "native", event, [sent_telegram], NOW)


def _whatsapp_configured():
    return types.SimpleNamespace(
        telegram=None,
        webhook=None,
        whatsapp=types.SimpleNamespace(phone="+34123123123", apikey="k"),
    )


def test_send_routes_a_whatsapp_channel_to_callmebot() -> None:
    from findplus.alerts.dispatch_core import Rule
    from findplus.alerts.dispatch_send import _send

    rule = Rule(
        id=1,
        name="r",
        place_id=1,
        group_id=None,
        device_id="dev1",
        on_enter=True,
        on_exit=True,
        channels=["whatsapp"],
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
    )
    ok = types.SimpleNamespace(success=True, status_code=200, error=None)
    with patch("findplus.alerts.channels.whatsapp_callmebot.send", return_value=ok) as wa_mock:
        result = _send("whatsapp", rule, _device_event(), "device", "msg", _whatsapp_configured())
    assert result is ok
    assert wa_mock.call_args[0] == ("msg", "+34123123123", "k")


def test_send_falls_through_to_none_when_whatsapp_is_unconfigured() -> None:
    from findplus.alerts.dispatch_core import Rule
    from findplus.alerts.dispatch_send import _send

    rule = Rule(
        id=1,
        name="r",
        place_id=1,
        group_id=None,
        device_id="dev1",
        on_enter=True,
        on_exit=True,
        channels=["whatsapp"],
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
    )
    unconfigured = types.SimpleNamespace(telegram=None, webhook=None, whatsapp=None)
    assert _send("whatsapp", rule, _device_event(), "device", "msg", unconfigured) is None

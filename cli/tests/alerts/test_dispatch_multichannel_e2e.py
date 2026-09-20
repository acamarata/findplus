"""End to end: one rule, three channels, one event, three delivery rows.

Purpose    : T1-T6 each tested their own unit. Nothing proved that a single
             rule targeting telegram + whatsapp + native produces exactly one
             delivery per channel with the right status, or that the cooldown
             is genuinely per channel once real sends are in play.
Constraints: No socket. Both channel senders are monkeypatched; the native
             channel never calls one by construction.
"""

from __future__ import annotations

import types
from datetime import timedelta
from unittest.mock import patch

from findplus.alerts import dispatch
from findplus.alerts.channels_field import format_channels
from findplus.db.models_alerts import AlertDelivery, AlertRule

from ._helpers import NOW, _seed_pending_place_event, _seed_place_and_device

COOLDOWN_MINUTES = 30
#: Well inside COOLDOWN_MINUTES: the second pass must be suppressed for the two
#: sending channels, which is the whole point of the test.
SECOND_PASS_AFTER = timedelta(minutes=5)


def _all_channels_configured():
    return types.SimpleNamespace(
        telegram=types.SimpleNamespace(bot_token="t", chat_id="1"),
        webhook=None,
        whatsapp=types.SimpleNamespace(phone="+34123123123", apikey="k"),
    )


def _ok():
    return types.SimpleNamespace(success=True, status_code=200, error=None)


def _three_channel_rule(session) -> AlertRule:
    _seed_place_and_device(session)
    rule = AlertRule(
        name="everything",
        place_id=1,
        device_id="dev1",
        on_enter=True,
        on_exit=True,
        channels=format_channels(["telegram", "whatsapp", "native"]),
        cooldown_minutes=COOLDOWN_MINUTES,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    session.add(rule)
    session.commit()
    return rule


def _rows(session):
    return session.query(AlertDelivery).order_by(AlertDelivery.id).all()


def _run(session, settings, now):
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_all_channels_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_ok()) as tg,
        patch("findplus.alerts.channels.whatsapp_callmebot.send", return_value=_ok()) as wa,
    ):
        dispatch.process(dispatch.load_pending_events(session), session, settings, now=now)
        return tg, wa


def test_one_event_produces_one_delivery_per_channel(session, settings_enabled) -> None:
    rule = _three_channel_rule(session)
    _seed_pending_place_event(session, 1, NOW)
    session.commit()
    _run(session, settings_enabled, NOW)
    rows = _rows(session)
    assert {r.channel for r in rows} == {"telegram", "whatsapp", "native"}
    assert all(r.rule_id == rule.id for r in rows)
    assert len({r.event_id for r in rows}) == 1


def test_each_row_carries_its_own_channels_outcome(session, settings_enabled) -> None:
    _three_channel_rule(session)
    _seed_pending_place_event(session, 1, NOW)
    session.commit()
    _run(session, settings_enabled, NOW)
    by_channel = {r.channel: r for r in _rows(session)}
    assert by_channel["telegram"].status == "sent"
    assert by_channel["whatsapp"].status == "sent"
    assert by_channel["native"].status == "queued"
    assert by_channel["native"].error is None


def test_both_senders_are_called_exactly_once(session, settings_enabled) -> None:
    _three_channel_rule(session)
    _seed_pending_place_event(session, 1, NOW)
    session.commit()
    telegram_mock, whatsapp_mock = _run(session, settings_enabled, NOW)
    assert telegram_mock.call_count == 1
    assert whatsapp_mock.call_count == 1


def test_inside_the_cooldown_only_native_fires_again(session, settings_enabled) -> None:
    """Sent rows start a cooldown; a queued one cannot, and cooldown is per channel."""
    _three_channel_rule(session)
    _seed_pending_place_event(session, 1, NOW)
    session.commit()
    _run(session, settings_enabled, NOW)

    later = NOW + SECOND_PASS_AFTER
    assert timedelta(minutes=COOLDOWN_MINUTES) > SECOND_PASS_AFTER
    _seed_pending_place_event(session, 1, later)
    session.commit()
    telegram_mock, whatsapp_mock = _run(session, settings_enabled, later)

    assert telegram_mock.call_count == 0
    assert whatsapp_mock.call_count == 0
    queued = [r for r in _rows(session) if r.status == "queued"]
    assert [r.channel for r in queued] == ["native", "native"]


def test_past_the_cooldown_every_channel_fires_again(session, settings_enabled) -> None:
    _three_channel_rule(session)
    _seed_pending_place_event(session, 1, NOW)
    session.commit()
    _run(session, settings_enabled, NOW)

    later = NOW + timedelta(minutes=COOLDOWN_MINUTES + 1)
    _seed_pending_place_event(session, 1, later)
    session.commit()
    telegram_mock, whatsapp_mock = _run(session, settings_enabled, later)
    assert telegram_mock.call_count == 1
    assert whatsapp_mock.call_count == 1
    assert len(_rows(session)) == 6

"""alerts/dispatch.py: group-rule vs device-rule suppression matrix.

Split out of test_dispatch.py (PRI rule 7, <=300 lines/file). Shared
seed/builder helpers live in _helpers.py; shared fixtures (settings_enabled)
in conftest.py.
"""

from __future__ import annotations

import types
from unittest.mock import patch

from findplus.alerts.dispatch import process
from findplus.db.models_alerts import AlertRule

from ._helpers import NOW, _device_event, _seed_group, _seed_place_and_device, _telegram_configured


def test_group_rule_suppresses_device_rule(session, settings_enabled) -> None:
    _seed_place_and_device(session)
    _seed_group(session)
    device_rule = AlertRule(
        name="device-rule",
        place_id=1,
        device_id="dev1",
        channels="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    group_rule = AlertRule(
        name="group-rule",
        place_id=1,
        group_id=1,
        channels="telegram",
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
        channels="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    group_rule = AlertRule(
        name="group-rule",
        place_id=1,
        group_id=1,
        channels="telegram",
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


def test_group_rule_any_place_suppresses_place_scoped_device_rule(
    session, settings_enabled
) -> None:
    """None-vs-set: a group rule with place_id=None covers every place (engines.md
    match()), so it must still suppress a device rule scoped to the event's place."""
    _seed_place_and_device(session)
    _seed_group(session)
    device_rule = AlertRule(
        name="device-rule",
        place_id=1,
        device_id="dev1",
        channels="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    group_rule = AlertRule(
        name="group-rule-any-place",
        place_id=None,
        group_id=1,
        channels="telegram",
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


def test_place_scoped_group_rule_suppresses_any_place_device_rule(
    session, settings_enabled
) -> None:
    """Set-vs-None: a place-scoped group rule must suppress an any-place device
    rule when the event actually crosses that group rule's place."""
    _seed_place_and_device(session)
    _seed_group(session)
    device_rule = AlertRule(
        name="device-rule-any-place",
        place_id=None,
        device_id="dev1",
        channels="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    group_rule = AlertRule(
        name="group-rule",
        place_id=1,
        group_id=1,
        channels="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    session.add_all([device_rule, group_rule])
    session.commit()

    event = _device_event(group_ids=[1], place_id=1)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send") as send_mock,
    ):
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        process([event], session, settings_enabled, now=NOW)
        assert send_mock.call_count == 0

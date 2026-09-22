"""alerts/dispatch.py: cooldown scoped per place (device rules and group rules).

Purpose : Cover the E6 CR-C ruling (engines.md "Rulings 2026-09-19" / "Cooldown
          key") -- in_cooldown() must key on (rule.id, place_id, subject), not
          just (rule.id, event_kind), so a place_id=None rule cools down per
          place instead of across every place. Split out of test_dispatch.py
          (PRI hard rule: <=300 lines/file) the same way dispatch_core.py was
          split out of dispatch.py. Group-event content/dispatch tests (not
          cooldown-scoped) live in test_dispatch_group_events.py; shared
          seed/builder helpers in _helpers.py; shared fixtures in conftest.py.
Inputs  : Real DB rows (place_events / group_place_events / alert_rules) via
          the `session` fixture -- no mocked ORM.
Outputs : n/a (pytest assertions).
Constraints: Never touches the network or the real ~/.findplus (conftest.py
          fixtures already enforce this).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from findplus.alerts.dispatch import load_pending_events, process
from findplus.db.models_alerts import AlertDelivery

from ._helpers import (
    NOW,
    _group_event,
    _rule,
    _seed_group,
    _seed_group_place_event,
    _seed_pending_place_event,
    _seed_place,
    _seed_place_and_device,
    _send_ok,
    _telegram_configured,
)


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


def test_failed_delivery_does_not_start_the_cooldown(session, settings_enabled) -> None:
    """A failed send must not suppress the very next crossing at the same key.

    1.0 has no delivery retry (the source event is stamped notified_at either
    way), so if a failed send also started the cooldown, one transient error
    would silently drop the tag's next alert too, for the whole window.
    """
    _seed_place_and_device(session)
    session.add(_rule())
    session.commit()

    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch(
            "findplus.alerts.channels.telegram.send",
            side_effect=RuntimeError("telegram: bot was blocked or kicked (403)"),
        ),
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    assert session.query(AlertDelivery).filter_by(status="failed").count() == 1

    later = NOW + timedelta(minutes=5)
    _seed_pending_place_event(session, place_id=1, observed_at=later)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()) as send_mock,
    ):
        process(load_pending_events(session), session, settings_enabled, now=later)
        assert send_mock.call_count == 1  # not suppressed by the earlier failure

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

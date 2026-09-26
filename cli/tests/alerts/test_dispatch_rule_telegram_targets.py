"""Per-rule Telegram target subset (WP10, gap-audit P13): dispatch.py sends
only to the rule's own picked chats when `telegram_targets` is set, and
records a clear "skipped" row -- never a send attempt -- when the rule's
subset (after intersecting with what is actually saved) is empty.

Constraints: No socket -- findplus.alerts.channels.telegram.send is
             monkeypatched, matching test_dispatch_multitarget.py's own
             posture.
"""

from __future__ import annotations

import types
from unittest.mock import patch

from findplus.alerts.dispatch import load_pending_events, process
from findplus.db.models_alerts import AlertDelivery, AlertRule

from ._helpers import NOW, _seed_pending_place_event, _seed_place_and_device


def _telegram_multi(*chat_ids: str):
    return types.SimpleNamespace(
        telegram=types.SimpleNamespace(bot_token="t", chat_ids=chat_ids), webhook=None
    )


def _ok(*_a, **_kw):
    return types.SimpleNamespace(success=True, status_code=200, error=None)


def _rows(session) -> list[AlertDelivery]:
    return session.query(AlertDelivery).order_by(AlertDelivery.target).all()


def _make_rule(session, telegram_targets: str | None) -> AlertRule:
    _seed_place_and_device(session)
    rule = AlertRule(
        name="r1",
        place_id=1,
        device_id="dev1",
        on_enter=True,
        on_exit=True,
        channels="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        telegram_targets=telegram_targets,
        created_at=NOW,
    )
    session.add(rule)
    session.commit()
    return rule


def test_null_telegram_targets_sends_to_every_saved_chat(session, settings_enabled) -> None:
    """The default (no rule ever narrowed it) -- unchanged pre-WP10 fan-out."""
    _make_rule(session, telegram_targets=None)
    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_multi("1", "2", "3")),
        patch("findplus.alerts.channels.telegram.send", side_effect=_ok) as send_mock,
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    rows = _rows(session)
    assert [r.target for r in rows] == ["1", "2", "3"]
    assert send_mock.call_count == 3


def test_explicit_subset_sends_only_to_the_picked_chats(session, settings_enabled) -> None:
    """The owner's own ask: "Kid left Home" to one parent only."""
    _make_rule(session, telegram_targets="2")
    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_multi("1", "2", "3")),
        patch("findplus.alerts.channels.telegram.send", side_effect=_ok) as send_mock,
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    rows = _rows(session)
    assert [r.target for r in rows] == ["2"]
    assert rows[0].status == "sent"
    assert send_mock.call_count == 1


def test_subset_silently_drops_a_target_no_longer_saved(session, settings_enabled) -> None:
    """A target removed from the account since the rule picked it drops
    from the send, never errors -- routes_alerts_telegram.py's own prune
    keeps the stored column itself in sync; dispatch.py's own intersection
    is the second, independent safety net."""
    _make_rule(session, telegram_targets="2,9")
    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_multi("1", "2", "3")),
        patch("findplus.alerts.channels.telegram.send", side_effect=_ok),
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    rows = _rows(session)
    assert [r.target for r in rows] == ["2"]


def test_explicit_empty_subset_skips_telegram_with_a_clear_reason(
    session, settings_enabled
) -> None:
    """The owner explicitly picked no chat (UI: unticked every checkbox under
    "Choose specific chats") -- one skipped row, no send attempt, and never
    a silent fall-back to "all"."""
    _make_rule(session, telegram_targets="")
    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_multi("1", "2")),
        patch("findplus.alerts.channels.telegram.send", side_effect=_ok) as send_mock,
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    rows = _rows(session)
    assert len(rows) == 1
    assert rows[0].status == "skipped"
    assert rows[0].target == ""
    assert "no telegram chats selected" in rows[0].error.lower()
    assert send_mock.call_count == 0


def test_empty_subset_after_every_picked_target_was_removed_also_skips(
    session, settings_enabled
) -> None:
    """Same skip path as an explicit `[]`, reached instead by every id in a
    non-empty subset having since been removed from the saved list."""
    _make_rule(session, telegram_targets="9,10")
    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_multi("1", "2")),
        patch("findplus.alerts.channels.telegram.send", side_effect=_ok) as send_mock,
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    rows = _rows(session)
    assert len(rows) == 1
    assert rows[0].status == "skipped"
    assert send_mock.call_count == 0

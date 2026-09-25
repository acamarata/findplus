"""Telegram multi-target dispatch: one delivery row per target, one failing
target never stops the others, and a retry only ever touches its own target.

Purpose    : The owner asked for a Telegram rule to notify a group, a person,
             or several people (comma-delimited). dispatch.py fans a
             telegram send out over every configured target
             (channels_cfg.telegram.chat_ids); this proves the fan-out,
             per-target failure isolation, and per-target retry.
Constraints: No socket -- findplus.alerts.channels.telegram.send is
             monkeypatched with a side_effect keyed by the chat_id argument,
             never a blanket return_value, so each target's own outcome is
             independently controllable.
"""

from __future__ import annotations

import types
from datetime import timedelta
from unittest.mock import patch

from findplus.alerts.dispatch import load_pending_events, process
from findplus.alerts.retry import process_retries
from findplus.db.models_alerts import AlertDelivery

from ._helpers import NOW, _seed_pending_place_event


def _telegram_multi(*chat_ids: str):
    return types.SimpleNamespace(
        telegram=types.SimpleNamespace(bot_token="t", chat_ids=chat_ids), webhook=None
    )


def _ok(*_a, **_kw):
    return types.SimpleNamespace(success=True, status_code=200, error=None)


def _timeout(*_a, **_kw):
    return types.SimpleNamespace(success=False, status_code=None, error="timeout")


def _rows(session) -> list[AlertDelivery]:
    return session.query(AlertDelivery).order_by(AlertDelivery.target).all()


def test_three_targets_produce_three_delivery_rows(rule_row, session, settings_enabled) -> None:
    """The owner's own phrasing: a group, a person, or several people."""
    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch(
            "findplus.alerts.store.load_alerts", return_value=_telegram_multi("1", "-100222", "@p3")
        ),
        patch("findplus.alerts.channels.telegram.send", side_effect=_ok) as send_mock,
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    rows = _rows(session)
    assert [r.target for r in rows] == ["-100222", "1", "@p3"]
    assert all(r.channel == "telegram" and r.status == "sent" for r in rows)
    assert send_mock.call_count == 3


def test_one_failing_target_does_not_stop_the_others(rule_row, session, settings_enabled) -> None:
    def _send(text, bot_token, chat_id, **kw):
        if chat_id == "bad":
            return types.SimpleNamespace(success=False, status_code=403, error="blocked")
        return _ok()

    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch(
            "findplus.alerts.store.load_alerts",
            return_value=_telegram_multi("good1", "bad", "good2"),
        ),
        patch("findplus.alerts.channels.telegram.send", side_effect=_send),
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    by_target = {r.target: r for r in _rows(session)}
    assert by_target["good1"].status == "sent"
    assert by_target["good2"].status == "sent"
    assert by_target["bad"].status == "failed"
    assert by_target["bad"].error == "blocked"


def test_transient_failure_on_one_target_schedules_only_that_targets_retry(
    rule_row, session, settings_enabled
) -> None:
    def _send(text, bot_token, chat_id, **kw):
        return _timeout() if chat_id == "flaky" else _ok()

    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_multi("stable", "flaky")),
        patch("findplus.alerts.channels.telegram.send", side_effect=_send),
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    by_target = {r.target: r for r in _rows(session)}
    assert by_target["stable"].status == "sent"
    assert by_target["flaky"].status == "retrying"


def test_retry_only_resends_to_the_failed_target_never_the_one_that_succeeded(
    rule_row, session, settings_enabled
) -> None:
    """The exact ask: "retries apply per failed target, not by resending to
    targets that already succeeded"."""
    calls: list[str] = []

    def _send(text, bot_token, chat_id, **kw):
        calls.append(chat_id)
        return _timeout() if chat_id == "flaky" else _ok()

    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_multi("stable", "flaky")),
        patch("findplus.alerts.channels.telegram.send", side_effect=_send),
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    assert sorted(calls) == ["flaky", "stable"]
    calls.clear()

    due = NOW + timedelta(minutes=1)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_multi("stable", "flaky")),
        patch("findplus.alerts.channels.telegram.send", side_effect=_send),
    ):
        process_retries(session, now=due)
    # Only the failed target's row is due for retry -- "stable" already sent
    # and is never touched again.
    assert calls == ["flaky"]
    session.expire_all()
    by_target = {r.target: r for r in _rows(session)}
    assert by_target["flaky"].status == "retrying"
    assert by_target["stable"].status == "sent"
    assert by_target["stable"].attempts == 1


def test_retry_eventually_succeeds_and_stops_retrying(rule_row, session, settings_enabled) -> None:
    outcomes = iter([_timeout(), _ok()])

    def _send(text, bot_token, chat_id, **kw):
        return next(outcomes)

    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_multi("only")),
        patch("findplus.alerts.channels.telegram.send", side_effect=_send),
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    row = _rows(session)[0]
    assert row.status == "retrying"

    due = NOW + timedelta(minutes=1)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_multi("only")),
        patch("findplus.alerts.channels.telegram.send", side_effect=_send),
    ):
        process_retries(session, now=due)
    session.expire_all()
    row = _rows(session)[0]
    assert row.status == "sent"


def test_no_configured_targets_falls_back_to_a_single_skipped_row(
    rule_row, session, settings_enabled
) -> None:
    """A rule listing telegram with the channel unconfigured (no targets at
    all) must still produce exactly one "skipped" row, not zero rows and not
    one row per phantom target."""
    unconfigured = types.SimpleNamespace(telegram=None, webhook=None)
    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with patch("findplus.alerts.store.load_alerts", return_value=unconfigured):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
    rows = _rows(session)
    assert len(rows) == 1
    assert rows[0].status == "skipped"
    assert rows[0].target == ""

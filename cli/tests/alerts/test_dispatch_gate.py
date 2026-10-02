"""alerts/dispatch_gate.py: burst limit, rule age, event age, story order (uat116 #1, #14)."""

from __future__ import annotations

import types
from datetime import timedelta
from unittest.mock import patch

from findplus.alerts.dispatch import BURST_REASON, process
from findplus.alerts.dispatch_events import _story_order
from findplus.alerts.dispatch_gate import BURST_LIMIT, is_stale, predates
from findplus.db.models_alerts import AlertDelivery

from ._helpers import (
    NOW,
    _device_event,
    _rule,
    _seed_place_and_device,
    _send_ok,
    _telegram_configured,
)


def _dispatch(session, events, now=NOW):
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()) as send,
    ):
        process(events, session, types.SimpleNamespace(alerts_enabled=True), now=now)
    return [c.args[0] for c in send.call_args_list]


def test_a_burst_sends_five_then_one_summary(tmp_db, session) -> None:
    _seed_place_and_device(session)
    session.add(_rule(cooldown_minutes=0))
    session.commit()
    events = [_device_event(place_event_id=i, observed_at=NOW + timedelta(seconds=i))
              for i in range(1, 9)]  # fmt: skip
    sent = _dispatch(session, events, now=NOW + timedelta(minutes=1))
    assert len(sent) == BURST_LIMIT + 1
    assert sent[-1].startswith("3 more arrivals and departures happened earlier")
    held = session.query(AlertDelivery).filter_by(status="skipped").all()
    assert len(held) == 3 and {h.error for h in held} == {BURST_REASON}


def test_the_limit_counts_what_this_chat_got_a_moment_ago(tmp_db, session) -> None:
    _seed_place_and_device(session)
    session.add(_rule(cooldown_minutes=0))
    session.commit()
    first = [_device_event(place_event_id=i) for i in range(1, 5)]
    assert len(_dispatch(session, first)) == 4
    later = [_device_event(place_event_id=i) for i in range(5, 8)]
    sent = _dispatch(session, later, now=NOW + timedelta(seconds=20))
    assert len(sent) == 2  # one more, then the summary
    assert sent[-1].startswith("2 more arrivals")


def test_a_rule_never_sends_what_happened_before_it_existed(tmp_db, session) -> None:
    _seed_place_and_device(session)
    session.add(_rule(created_at=NOW + timedelta(minutes=5)))
    session.commit()
    assert _dispatch(session, [_device_event()], now=NOW + timedelta(minutes=6)) == []


def test_age_is_counted_from_when_find_plus_learned_of_it() -> None:
    late = _device_event(observed_at=NOW - timedelta(minutes=40), fetched_at=NOW)
    assert not is_stale(late, NOW + timedelta(minutes=2), 30)
    assert is_stale(late, NOW + timedelta(minutes=31), 30)
    ancient = _device_event(observed_at=NOW - timedelta(hours=3), fetched_at=NOW)
    assert is_stale(ancient, NOW, 30)


def test_predates_ignores_a_rule_with_no_creation_time() -> None:
    rule = types.SimpleNamespace(created_at=None)
    assert not predates(rule, _device_event())


def test_same_instant_departure_is_sent_before_the_arrival() -> None:
    arrive = _device_event(place_event_id=1, place_name="Grandma's", event_type="ENTER")
    leave = _device_event(place_event_id=2, place_name="Home", event_type="EXIT")
    earlier = _device_event(place_event_id=3, event_type="ENTER", observed_at=NOW - timedelta(1))
    ordered = sorted([arrive, leave, earlier], key=_story_order)
    assert [e.place_event_id for e in ordered] == [3, 2, 1]


def test_a_bad_max_age_setting_falls_back_to_the_default(tmp_db, session) -> None:
    from findplus.alerts.dispatch_gate import MAX_AGE_MINUTES, MAX_AGE_SETTING, max_age_minutes
    from findplus.state import set_setting

    set_setting(session, MAX_AGE_SETTING, "soon")
    assert max_age_minutes(session) == MAX_AGE_MINUTES
    set_setting(session, MAX_AGE_SETTING, "45")
    assert max_age_minutes(session) == 45


def test_a_failed_summary_never_raises_and_whatsapp_gets_one_too() -> None:
    from findplus.alerts.dispatch_gate import Burst, send_summaries

    burst = Burst(None, NOW)
    burst.hold("telegram", "1")
    burst.hold("whatsapp", "")
    burst.hold("webhook", "")  # not a chat: nothing to send, still logged
    cfg = types.SimpleNamespace(
        telegram=types.SimpleNamespace(bot_token="t", chat_ids=("1",)),
        whatsapp=types.SimpleNamespace(phone="+1", apikey="k"),
    )
    with (
        patch("findplus.alerts.channels.telegram.send", side_effect=RuntimeError("boom")),
        patch("findplus.alerts.channels.whatsapp_callmebot.send", return_value=_send_ok()) as wa,
    ):
        send_summaries(burst, cfg)
    assert wa.call_args.args[0].startswith("1 more arrival or departure happened earlier")

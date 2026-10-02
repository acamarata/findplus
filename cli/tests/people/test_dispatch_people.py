"""Person events and left-behind episodes through the real alert pipeline (spec § 5)."""

from __future__ import annotations

import types
from datetime import timedelta
from unittest.mock import patch

from findplus.alerts import dispatch
from findplus.alerts.default_rules import build_rule
from findplus.db.models import GroupPlaceEvent
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.honesty import ALERTS_LATENCY

from ._helpers import GRANDMA, HOME, Timeline, at, overnight, seed_person, seed_places
from .test_scenarios_left_behind import _bag_stays_at_school

SETTINGS = types.SimpleNamespace(alerts_enabled=True)


def _telegram():
    return types.SimpleNamespace(
        telegram=types.SimpleNamespace(bot_token="t", chat_ids=("1",)), webhook=None, whatsapp=None
    )


def _run_dispatch(session, now):
    ok = types.SimpleNamespace(success=True, status_code=200, error=None)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram()),
        patch("findplus.alerts.channels.telegram.send", return_value=ok) as send,
    ):
        dispatch.process(dispatch.load_pending_events(session), session, SETTINGS, now=now)
    return [c.args[0] for c in send.call_args_list]


def _default_rules(session, places):
    """The default rules, created the day before the scenario: a rule never
    sends a crossing from before it existed (uat116 #1)."""
    for place in places.values():
        rule = build_rule(place, ["telegram"], True)
        rule.created_at = at(0, 0, day=-1)
        session.add(rule)
    session.commit()


def _to_grandmas(session, stagger=1):
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(9, 0))
    for n, d in enumerate(["zr", "zb", "zk", "zw"]):
        tl.walk([d], HOME, GRANDMA, at(9, 0) + timedelta(minutes=n * stagger), at(9, 40))
    tl.ingest(session)


def test_four_trackers_crossing_grandmas_send_one_message(session, pinned_tz):
    pinned_tz("UTC")
    places = seed_places(session)
    sam = seed_person(session)
    _default_rules(session, places)
    _to_grandmas(session)
    rows = session.query(GroupPlaceEvent).filter_by(group_id=sam.id, place_id=3).all()
    assert len(rows) == 1
    sent = _run_dispatch(session, now=at(9, 44))
    arrivals = [t for t in sent if "Grandma's" in t.splitlines()[0]]
    assert len(arrivals) == 1
    assert arrivals[0].startswith("Sam just arrived at Grandma's")
    assert arrivals[0].endswith(ALERTS_LATENCY)


def test_late_report_says_the_time_not_just(session, pinned_tz):
    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session)
    _default_rules(session, places)
    _to_grandmas(session)
    sent = _run_dispatch(session, now=at(10, 10))
    first = next(t for t in sent if "Grandma's" in t.splitlines()[0]).splitlines()
    assert first[0].startswith("Sam arrived at Grandma's at 9:")  # same day: no date
    assert first[1].startswith("Seen by ") and "min late" in first[1]
    assert "just" not in first[0]


def test_leaving_home_says_has_just_left_and_names_what_stayed(session, pinned_tz):
    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session)
    _default_rules(session, places)
    _bag_stays_at_school(Timeline()).ingest(session)
    exits = [t for t in _run_dispatch(session, now=at(15, 32)) if t.startswith("Sam left School")]
    assert len(exits) == 1
    assert "Sam's bag stayed at School." in exits[0]


def test_left_behind_alerts_once_away_from_home(session, pinned_tz):
    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session)
    _default_rules(session, places)
    _bag_stays_at_school(Timeline()).ingest(session)
    sent = _run_dispatch(session, now=at(15, 45))
    left = [t for t in sent if "looks left at" in t]
    assert len(left) == 1, sent
    assert left[0].startswith("Sam's bag looks left at School. Last seen there at 3:")
    assert left[0].endswith(ALERTS_LATENCY)
    assert "White" not in "".join(left)  # the shoes at Home never alert
    assert session.query(AlertDelivery).filter_by(event_kind="left_behind").count() == 1
    assert [t for t in _run_dispatch(session, now=at(19, 0)) if "looks left" in t] == []


def test_left_behind_alerts_can_be_turned_off(session, pinned_tz):
    from findplus.state import set_setting

    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session)
    _default_rules(session, places)
    set_setting(session, "people.left_behind_alerts", "0")
    _bag_stays_at_school(Timeline()).ingest(session)
    assert [t for t in _run_dispatch(session, now=at(18, 30)) if "looks left" in t] == []


def test_all_people_rule_suppresses_the_device_rules_of_that_persons_trackers(session, pinned_tz):
    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session)
    _default_rules(session, places)
    session.add(
        AlertRule(name="red shoes", place_id=None, device_id="zr", on_enter=True, on_exit=True,
                  channels="telegram", cooldown_minutes=0, enabled=True,
                  also_notify_members=False, created_at=at(0))
    )  # fmt: skip
    session.commit()
    _to_grandmas(session)
    sent = _run_dispatch(session, now=at(9, 50))
    assert not any(t.startswith("Sam Shoes Red") for t in sent)


def test_all_people_cooldown_is_per_person(session, pinned_tz):
    """Sam arriving must not cool down Jamie's arrival under the same rule."""
    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session)
    seed_person(session, "Jamie", {"am": "Jamie"})
    rule = build_rule(places["Grandma's"], ["telegram"], True)
    rule.cooldown_minutes, rule.created_at = 60, at(0, 0, day=-1)
    session.add(rule)
    session.commit()
    _to_grandmas(session)
    tl = Timeline()
    overnight(tl, ["am"], end=at(9, 10))
    tl.walk(["am"], HOME, GRANDMA, at(9, 10), at(9, 45))
    tl.ingest(session)
    sent = _run_dispatch(session, now=at(9, 50))
    firsts = sorted(t.splitlines()[0].split(" ")[0] for t in sent)
    assert firsts == ["Jamie", "Sam"]


def test_retry_renders_the_same_person_text(session, pinned_tz):
    from findplus.alerts.retry import _load_event

    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session)
    _default_rules(session, places)
    _to_grandmas(session)
    sent = _run_dispatch(session, now=at(9, 50))
    gpe = session.query(GroupPlaceEvent).filter_by(place_id=3).one()
    event = _load_event(session, "group", gpe.id)
    assert dispatch.render_message(event, at(9, 50)) in sent

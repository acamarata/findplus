"""Switching alerts on never floods a chat with history (uat116 #1).

Three weeks of school runs are ingested with no rule. The default rules are then
created, the person is already on the way, and one new sighting arrives. Only
that one arrival may be sent; every older crossing is stamped notified and
never comes back.
"""

from __future__ import annotations

from datetime import timedelta

from findplus.alerts.default_rules import build_rule
from findplus.db.models import GroupPlaceEvent
from findplus.honesty import ALERTS_LATENCY

from ._helpers import HOME, SCHOOL, Timeline, at, seed_person, seed_places
from .test_dispatch_people import _run_dispatch

TRACKERS = {"zr": "Robin", "zb": "Robin Bag"}
MIDWAY = ((HOME[0] + SCHOOL[0]) / 2, (HOME[1] + SCHOOL[1]) / 2)


def _school_day(tl: Timeline, day: int, until_home: bool = True) -> None:
    devices = list(TRACKERS)
    tl.stay(devices, HOME, at(0, 30, day), at(7, 30, day), every=120)
    tl.walk(devices, HOME, SCHOOL, at(7, 30, day), at(8, 0, day), every=10)
    if not until_home:
        return
    tl.stay(devices, SCHOOL, at(8, 10, day), at(15, 0, day), every=120)
    tl.walk(devices, SCHOOL, HOME, at(15, 0, day), at(15, 30, day), every=10)
    tl.stay(devices, HOME, at(15, 40, day), at(23, 0, day), every=120)


def _history(session):
    places = seed_places(session)
    robin = seed_person(session, "Robin", TRACKERS)
    tl = Timeline()
    for day in range(21):
        _school_day(tl, day)
    tl.ingest(session)
    tl.stay(list(TRACKERS), HOME, at(0, 30, 21), at(7, 30, 21), every=120)
    tl.walk(list(TRACKERS), HOME, MIDWAY, at(7, 30, 21), at(7, 50, 21), every=10)
    tl.ingest(session)
    return places, robin


def _rules_created(session, places, when):
    for place in places.values():
        rule = build_rule(place, ["telegram"], True)
        rule.created_at = when
        session.add(rule)
    session.commit()


def test_new_rules_over_three_weeks_of_history_send_one_message(session, pinned_tz):
    pinned_tz("UTC")
    places, robin = _history(session)
    old = session.query(GroupPlaceEvent).filter_by(group_id=robin.id).count()
    assert old > 40  # the history really has crossings waiting
    _rules_created(session, places, at(7, 55, 21))
    Timeline().stay(list(TRACKERS), SCHOOL, at(8, 0, 21), at(8, 0, 21)).ingest(session, 2)
    sent = _run_dispatch(session, now=at(8, 3, 21))
    assert len(sent) == 1
    assert sent[0].startswith("Robin just arrived at School")
    assert sent[0].endswith(ALERTS_LATENCY)
    pending = session.query(GroupPlaceEvent).filter(GroupPlaceEvent.notified_at.is_(None))
    assert pending.count() == 0
    assert _run_dispatch(session, now=at(8, 4, 21)) == []


def test_old_rules_do_not_send_a_crossing_learned_long_ago(session, pinned_tz):
    """Dispatch was down for hours: what it missed is not news any more."""
    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session, "Robin", TRACKERS)
    _rules_created(session, places, at(0, 0, -1))
    tl = Timeline()
    _school_day(tl, 0, until_home=False)
    tl.ingest(session)
    assert _run_dispatch(session, now=at(10, 0)) == []
    assert session.query(GroupPlaceEvent).filter(GroupPlaceEvent.notified_at.is_(None)).count() == 0


def test_a_late_report_learned_just_now_still_alerts_with_its_time(session, pinned_tz):
    """Find Hub reports are often 10 to 40 minutes late: still news, said with the time."""
    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session, "Robin", TRACKERS)
    _rules_created(session, places, at(0, 0, -1))
    tl = Timeline()
    _school_day(tl, 0, until_home=False)
    tl.ingest(session, lag_minutes=25)
    sent = _run_dispatch(session, now=at(8, 0) + timedelta(minutes=27))
    assert any(t.startswith("Robin arrived at School at ") for t in sent)

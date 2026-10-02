"""Left-behind alerts follow the person setting, wherever the tracker is (uat116 #3).

Alex works at a spot with no saved place. The keys stay there while the phone,
watch and wallet go to Grandma's. The owner only has the default per-place
rules: the keys must still alert once, and an episode that nothing could send
must stay pending instead of being stamped notified with no delivery row.
"""

from __future__ import annotations

from datetime import timedelta

from findplus.alerts.default_rules import build_rule
from findplus.db.models_alerts import AlertDelivery
from findplus.db.models_people import LeftBehind

from ._helpers import GRANDMA, HOME, Timeline, at, overnight, seed_person, seed_places
from .test_dispatch_people import _run_dispatch

ALEX = {"ak": "Alex Keys", "aw": "Alex Wallet", "ap": "Alex Phone", "ah": "Alex Watch"}
WORK = (41.160000, -80.700000)  # ~7 km from Home, no saved place


def _keys_left_at_work(session):
    places = seed_places(session)
    seed_person(session, "Alex", ALEX)
    tl = Timeline()
    overnight(tl, list(ALEX), end=at(8, 0))
    tl.walk(list(ALEX), HOME, WORK, at(8, 0), at(8, 40), every=10)
    tl.stay(list(ALEX), WORK, at(8, 50), at(12, 0), every=20)
    tl.walk(["aw", "ap", "ah"], WORK, GRANDMA, at(12, 0), at(12, 40), every=10)
    tl.stay(["aw", "ap", "ah"], GRANDMA, at(12, 50), at(14, 0), every=10)
    tl.stay(["ak"], WORK, at(12, 10), at(14, 0), every=10)
    tl.ingest(session)
    row = session.query(LeftBehind).filter_by(device_id="ak", state="left_behind").one()
    assert row.place_id is None and row.confirmed_at is not None
    return places, row


def _rules(session, places):
    for place in places.values():
        rule = build_rule(place, ["telegram"], True)
        rule.created_at = at(0, 0, day=-1)
        session.add(rule)
    session.commit()


def test_keys_left_at_an_unnamed_spot_alert_once_on_the_default_rules(session, pinned_tz):
    pinned_tz("UTC")
    places, row = _keys_left_at_work(session)
    _rules(session, places)
    sent = _run_dispatch(session, now=row.confirmed_at + timedelta(minutes=2))
    left = [t for t in sent if "looks left at" in t]
    assert len(left) == 1, sent
    assert left[0].startswith("Alex's ") and "looks left at an unnamed spot." in left[0]
    assert session.query(AlertDelivery).filter_by(event_kind="left_behind").count() == 1
    session.refresh(row)
    assert row.notified_at is not None


def test_with_no_rule_the_episode_stays_pending_until_one_can_carry_it(session, pinned_tz):
    pinned_tz("UTC")
    places, row = _keys_left_at_work(session)
    first = row.confirmed_at + timedelta(minutes=1)
    assert [t for t in _run_dispatch(session, now=first) if "looks left" in t] == []
    session.refresh(row)
    assert row.notified_at is None
    assert session.query(AlertDelivery).filter_by(event_kind="left_behind").count() == 0
    _rules(session, places)
    sent = _run_dispatch(session, now=first + timedelta(minutes=3))
    assert len([t for t in sent if "looks left" in t]) == 1

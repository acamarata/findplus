"""Alert regressions from the 1.1.6 review: silenced, doubled or repeated messages.

Each case runs the real ingest -> person engine -> dispatch chain with a
patched Telegram send (no network) and checks exactly what a parent receives.
"""

from __future__ import annotations

from findplus.db.models_alerts import AlertRule

from ._helpers import GRANDMA, HOME, Timeline, at, overnight, seed_person, seed_places
from .test_dispatch_people import _default_rules, _run_dispatch


def _device_rule(session, device_id, name, place_id=None):
    session.add(
        AlertRule(name=name, place_id=place_id, device_id=device_id, on_enter=True, on_exit=True,
                  channels="telegram", cooldown_minutes=0, enabled=True,
                  also_notify_members=False, created_at=at(0))
    )  # fmt: skip
    session.commit()


def test_backfill_never_silences_a_tracker_alert_the_person_engine_did_not_replace(
    session, pinned_tz
):
    """The owner had "Sam Bag at Grandma's". After "Notify me" added the
    all-people rules, the bag going to Grandma's on its own (a sibling took
    it: no person event) must still send the bag's own alert."""
    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session)
    _default_rules(session, places)
    _device_rule(session, "zb", "bag at Grandma's", places["Grandma's"].id)
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(9, 0))
    tl.walk(["zb"], HOME, GRANDMA, at(9, 0), at(9, 40))
    tl.stay(["zr", "zk", "zw"], HOME, at(9, 5), at(9, 45), every=5)
    tl.ingest(session)
    sent = _run_dispatch(session, now=at(9, 50))
    assert [t.splitlines()[0] for t in sent] == ["Sam Bag arrived at Grandma's"]


def test_a_person_event_still_suppresses_the_trackers_own_alerts(session, pinned_tz):
    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session)
    _default_rules(session, places)
    _device_rule(session, "zr", "red shoes")
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(9, 0))
    tl.walk(["zr", "zb"], HOME, GRANDMA, at(9, 0), at(9, 40))
    tl.stay(["zk", "zw"], HOME, at(9, 5), at(9, 45), every=5)
    tl.ingest(session)
    sent = _run_dispatch(session, now=at(9, 50))
    assert not any(t.startswith("Sam Shoes Red") for t in sent), sent
    assert any(t.startswith("Sam arrived at Grandma's at ") for t in sent), sent


def test_suppression_needs_the_persons_own_event():
    """Pure: an all-people or person rule hides a tracker's alert only when the
    person recorded an event; a plain set (quorum) rule behaves as before."""
    import datetime

    from findplus.alerts.dispatch_core import DeviceEvent, Rule, suppressed_by_group

    def rule(i, **kw):
        base = dict(id=i, name="r", place_id=None, group_id=None, device_id=None, on_enter=True,
                    on_exit=True, channels=["telegram"], cooldown_minutes=0, enabled=True,
                    also_notify_members=False)  # fmt: skip
        return Rule(**{**base, **kw})

    def event(person_events):
        return DeviceEvent(1, 3, "Grandma's", "zb", "Sam Bag", "ENTER",
                           datetime.datetime(2026, 9, 21, tzinfo=datetime.UTC), None, "high",
                           group_ids=[7, 9], person_group_ids=[7],
                           person_event_group_ids=person_events)  # fmt: skip

    device = rule(1, device_id="zb")
    for other in (rule(2, all_people=True), rule(3, group_id=7)):
        assert not suppressed_by_group(device, event([]), [device, other])
        assert suppressed_by_group(device, event([7]), [device, other])
    quorum = rule(4, group_id=9)
    assert suppressed_by_group(device, event([]), [device, quorum])


def _bag_left_reporting_rarely(tl: Timeline) -> Timeline:
    """The owner's example, but the bag at School reports only every 100 min
    (its stale limit is 90): it goes quiet and comes back four times by 23:00."""
    from ._helpers import SCHOOL

    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(7, 40))
    tl.walk(["zr", "zb"], HOME, SCHOOL, at(7, 40), at(8, 10))
    tl.stay(["zr", "zb"], SCHOOL, at(8, 30), at(15, 0))
    tl.walk(["zr"], SCHOOL, HOME, at(15, 0), at(15, 30))
    tl.stay(["zr"], HOME, at(15, 33), at(23, 0))
    tl.stay(["zb"], SCHOOL, at(15, 20), at(15, 40), every=10)
    tl.stay(["zb"], SCHOOL, at(17, 20), at(23, 0), every=100)
    tl.stay(["zk", "zw"], HOME, at(8, 0), at(23, 0), every=30)
    return tl


def test_left_behind_alerts_once_even_when_the_bag_goes_quiet_and_comes_back(session, pinned_tz):
    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session)
    _default_rules(session, places)
    tl = _bag_left_reporting_rarely(Timeline())
    sent = []
    for hour in (16, 18, 20, 23):  # dispatch runs between the bag's reports
        part = Timeline()
        part.fixes = [f for f in tl.fixes if f[0] <= at(hour, 0)]
        tl.fixes = [f for f in tl.fixes if f[0] > at(hour, 0)]
        part.ingest(session)
        sent += _run_dispatch(session, now=at(hour, 1))
    assert len([t for t in sent if "looks left at School" in t]) == 1, sent


def test_notify_me_and_the_place_default_send_one_message_per_crossing(session, pinned_tz):
    """The Person page's "Notify me" (a rule for Sam, any place) and the place's
    default all-people rule both match Sam arriving: one message, not two."""
    from .test_dispatch_people import _to_grandmas

    pinned_tz("UTC")
    places = seed_places(session)
    sam = seed_person(session)
    _default_rules(session, places)
    session.add(
        AlertRule(name="Sam anywhere", place_id=None, group_id=sam.id, on_enter=True,
                  on_exit=True, channels="telegram", cooldown_minutes=0, enabled=True,
                  also_notify_members=False, created_at=at(0))
    )  # fmt: skip
    session.commit()
    _to_grandmas(session)
    sent = _run_dispatch(session, now=at(9, 50))
    arrivals = [t for t in sent if "arrived at Grandma's" in t.splitlines()[0]]
    assert len(arrivals) == 1, sent


def test_a_settle_wait_keeps_the_crossing_time_and_the_lead_trackers_lag(session, pinned_tz):
    """Sam reaches Grandma's at 9:40 and turns back at once. The EXIT waits out
    the 10-minute settle, but "left at" is the first sighting outside (9:43),
    and "reported ... late" belongs to the tracker seen there."""
    from findplus.db.models import GroupPlaceEvent, LocationObservation

    pinned_tz("UTC")
    places = seed_places(session)
    sam = seed_person(session)
    _default_rules(session, places)
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(9, 0))
    tl.walk(["zr", "zb"], HOME, GRANDMA, at(9, 0), at(9, 40))
    tl.walk(["zr", "zb"], GRANDMA, HOME, at(9, 41), at(10, 21), every=2)
    tl.stay(["zk", "zw"], HOME, at(9, 5), at(10, 20), every=10)
    tl.ingest(session)
    left = (
        session.query(GroupPlaceEvent)
        .filter_by(group_id=sam.id, place_id=places["Grandma's"].id, event_type="EXIT")
        .one()
    )
    assert left.observed_at == at(9, 43)
    seen = session.query(LocationObservation).filter_by(
        device_id=left.lead_device_id, observed_at=left.observed_at
    )
    assert seen.count() == 1
    text = next(t for t in _run_dispatch(session, now=at(10, 30)) if "left Grandma's" in t)
    assert "left Grandma's at Sep 21, 9:43 AM" in text
    assert "lag unknown" not in text and "5 min late" in text


def test_lag_falls_back_to_the_leads_first_sighting_after_the_event(session):
    """A person row whose lead has no sighting at exactly that instant still
    says when that tracker was next reported, never "reported unknown"."""
    from findplus.alerts.group_event_rows import group_events_by_ids
    from findplus.db.models import GroupPlaceEvent

    places = seed_places(session)
    sam = seed_person(session)
    tl = Timeline()
    tl.add("zr", HOME, at(9, 0)).add("zr", HOME, at(9, 20))
    tl.ingest(session)
    row = GroupPlaceEvent(group_id=sam.id, place_id=places["Home"].id, event_type="ENTER",
                          observed_at=at(9, 10), member_event_ids="[]", members_crossed=1,
                          members_considered=4, members_stale=0, confidence="high",
                          basis="person", lead_device_id="zr")  # fmt: skip
    session.add(row)
    session.flush()
    event = group_events_by_ids(session, [row.id])[row.id]
    assert event.fetched_at == at(9, 25)

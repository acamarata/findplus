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

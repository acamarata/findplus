"""Left-behind regressions from the 1.1.6 review (spec § 4): what counts as a
newer sighting of the person, which rules a left-behind alert uses, and pets."""

from __future__ import annotations

from findplus.db.models_people import LeftBehind

from ._helpers import HOME, SCHOOL, Timeline, at, overnight, seed_person, seed_places


def test_confirming_needs_two_newer_sightings_of_the_person_not_the_parked_trackers(session):
    """The bike and white shoes at Home report every 5 minutes; Sam's shoes only
    at 15:30 and 16:00 after he leaves School. The bag at School is confirmed
    left only after two of Sam's own sightings, never on the parked ones."""
    places = seed_places(session)
    seed_person(session)
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(7, 40))
    tl.walk(["zr", "zb"], HOME, SCHOOL, at(7, 40), at(8, 10))
    tl.stay(["zr", "zb"], SCHOOL, at(8, 30), at(15, 0))
    tl.walk(["zr"], SCHOOL, HOME, at(15, 0), at(15, 30), every=15)
    tl.stay(["zr"], HOME, at(16, 0), at(18, 0), every=30)
    tl.stay(["zb"], SCHOOL, at(15, 20), at(18, 0), every=10)
    tl.stay(["zk", "zw"], HOME, at(8, 0), at(18, 0), every=5)
    tl.ingest(session)
    row = session.query(LeftBehind).filter_by(device_id="zb", place_id=places["School"].id).one()
    assert row.state == "left_behind"
    assert row.confirmed_at >= at(16, 0), row.confirmed_at


def _bag_left_at_school(session):
    from .test_scenarios_left_behind import _bag_stays_at_school

    _bag_stays_at_school(Timeline()).ingest(session)


def _rule(session, name, place_id=None, group_id=None, all_people=True):
    from findplus.db.models_alerts import AlertRule

    session.add(
        AlertRule(name=name, place_id=place_id, group_id=group_id, all_people=all_people,
                  on_enter=True, on_exit=True, channels="telegram", cooldown_minutes=0,
                  enabled=True, also_notify_members=False, created_at=at(0))
    )  # fmt: skip
    session.commit()


def test_a_rule_for_one_place_still_carries_a_bag_left_elsewhere(session, pinned_tz):
    """The owner's only rule is for Grandma's. Left-behind alerts follow the
    person setting ("tell me when a tracker is left behind, anywhere"), not the
    rule's place: the bag left at School is sent once on that rule's channel
    (uat116 #3, reversing review r116's place filter)."""
    from .test_dispatch_people import _run_dispatch

    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session)
    _rule(session, "Arrivals and departures at Grandma's", place_id=places["Grandma's"].id)
    _bag_left_at_school(session)
    assert len([t for t in _run_dispatch(session, now=at(15, 45)) if "looks left" in t]) == 1


def test_pets_get_no_all_people_alerts_by_default(session, pinned_tz):
    """A cat crossing Home's edge all evening is not a message (spec Q8: pet
    alerts off by default). The all-people rules cover people only."""
    from .test_dispatch_people import _run_dispatch

    pinned_tz("UTC")
    places = seed_places(session)
    seed_person(session, "Whiskers", {"cat": "Whiskers Collar"}, kind="pet")
    for place in places.values():
        _rule(session, f"Arrivals and departures at {place.name}", place_id=place.id)
    tl = Timeline()
    overnight(tl, ["cat"], end=at(17, 0))
    for n in range(8):
        out = (HOME[0] + 0.006, HOME[1])
        tl.walk(["cat"], HOME, out, at(17, 0 + n * 30), at(17, 15 + n * 30), every=5)
        tl.walk(["cat"], out, HOME, at(17, 15 + n * 30), at(17, 30 + n * 30), every=5)
    tl.ingest(session)
    assert _run_dispatch(session, now=at(21, 30)) == []

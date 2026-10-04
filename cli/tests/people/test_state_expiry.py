"""A person state nothing confirms for 12 h becomes unknown, never a late false event (r122 O5)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from findplus.db.models import Place
from findplus.db.models_people import PersonPlaceState
from findplus.people.expiry import STATE_EXPIRY, expired

from ._day_helpers import NEAR_HOME
from ._helpers import HOME, SCHOOL, Timeline, at, overnight, person_events, seed_person, seed_places


def _states(session, group_id) -> dict[str, str]:
    rows = session.execute(
        select(Place.name, PersonPlaceState.state)
        .join(PersonPlaceState, PersonPlaceState.place_id == Place.id)
        .where(PersonPlaceState.group_id == group_id)
    ).all()
    return {name: state for name, state in rows}


def _bag_dies_at_school(tl: Timeline) -> Timeline:
    """The bag walks Sam to School and stops reporting at 9:00; the rest stay at Home."""
    overnight(tl, ["zb", "zk", "zr", "zw"], end=at(7, 40))
    tl.walk(["zb"], HOME, SCHOOL, at(7, 40), at(8, 10))
    tl.stay(["zb"], SCHOOL, at(8, 15), at(9, 0), every=15)
    tl.stay(["zk", "zr", "zw"], HOME, at(8, 0), at(7, 0, day=1), every=20)
    return tl


def test_the_pure_rule() -> None:
    t = at(9, 0)
    assert not expired(None, at(9, 0, day=5))  # never judged here without a time
    assert not expired(t, t + STATE_EXPIRY)
    assert expired(t, t + STATE_EXPIRY + timedelta(minutes=1))


def test_a_bag_that_died_at_school_never_reads_left_school_next_morning(session):
    seed_places(session)
    sam = seed_person(session)
    tl = _bag_dies_at_school(Timeline())
    tl.stay(["zb"], SCHOOL, at(8, 0, day=1), at(8, 5, day=1), every=5)  # it wakes up at School
    tl.walk(["zb"], SCHOOL, NEAR_HOME, at(8, 5, day=1), at(8, 40, day=1), every=5)
    tl.ingest(session)
    events = person_events(session, sam.id)
    assert [(e, p) for e, p, _ in events[:2]] == [("EXIT", "Home"), ("ENTER", "School")]
    assert not any(e == "EXIT" and p == "School" for e, p, _ in events)
    assert _states(session, sam.id)["School"] != "inside"


def test_the_held_state_survives_a_short_silence(session):
    """Within 12 h the hold stands: quiet shoes reporting again from Home still bring Sam home."""
    seed_places(session)
    sam = seed_person(session)
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(7, 40))
    tl.walk(["zr"], HOME, SCHOOL, at(7, 40), at(8, 10))
    tl.stay(["zr"], SCHOOL, at(8, 15), at(9, 0), every=15)
    tl.stay(["zb", "zk", "zw"], HOME, at(8, 0), at(16, 0), every=20)
    tl.add("zr", HOME, at(15, 40)).add("zr", HOME, at(15, 50))
    tl.ingest(session)
    names = [(e, p) for e, p, _ in person_events(session, sam.id)]
    assert ("EXIT", "School") in names and ("ENTER", "Home") in names


def test_a_long_quiet_day_at_home_does_not_lose_the_leave_event(session):
    """20 h of parked trackers confirm Home each time: the state never expires, so leaving reads."""
    seed_places(session)
    sam = seed_person(session)
    tl = Timeline().stay(["zb", "zk", "zr", "zw"], HOME, at(0, 0), at(20, 0), every=60)
    tl.walk(["zb", "zr"], HOME, SCHOOL, at(20, 0), at(20, 40), every=5)
    tl.stay(["zb", "zr"], SCHOOL, at(20, 45), at(21, 30), every=15)
    tl.ingest(session)
    assert [(e, p) for e, p, _ in person_events(session, sam.id)] == [
        ("EXIT", "Home"),
        ("ENTER", "School"),
    ]

"""Person events over whole synthetic days (spec § 11: zaid_school_day and friends).

Each scenario feeds every tracker's fixes in time order through the real
ingest -> geofence -> person hook chain and asserts the person-level rows.
"""

from __future__ import annotations

from findplus.db.models_people import LeftBehind, PersonPlaceState

from ._helpers import (
    GRANDMA,
    HOME,
    SCHOOL,
    Timeline,
    at,
    overnight,
    person_events,
    seed_person,
    seed_places,
)


def _school_day(tl: Timeline, carried=("zr", "zb"), parked=("zk", "zw")) -> Timeline:
    overnight(tl, [*carried, *parked], end=at(7, 40))
    tl.walk(carried, HOME, SCHOOL, at(7, 40), at(8, 10), every=5)
    tl.stay(carried, SCHOOL, at(8, 30), at(15, 0), every=20)
    tl.walk(carried, SCHOOL, HOME, at(15, 0), at(15, 30), every=5)
    tl.stay(carried, HOME, at(15, 33), at(17, 0), every=20)
    tl.stay(parked, HOME, at(8, 0), at(17, 0), every=30)
    return tl


def test_zaid_school_day_gives_exactly_four_person_events(session):
    seed_places(session)
    zaid = seed_person(session)
    _school_day(Timeline()).ingest(session)
    events = [(t, p) for t, p, _ in person_events(session, zaid.id)]
    assert events == [
        ("EXIT", "Home"),
        ("ENTER", "School"),
        ("EXIT", "School"),
        ("ENTER", "Home"),
    ]


def test_school_day_events_happen_at_the_right_times(session):
    seed_places(session)
    zaid = seed_person(session)
    _school_day(Timeline()).ingest(session)
    times = [when for _, _, when in person_events(session, zaid.id)]
    assert at(7, 40) < times[0] <= at(7, 55)
    assert at(8, 0) <= times[1] <= at(8, 10)
    assert at(15, 0) < times[2] <= at(15, 15)
    assert at(15, 20) <= times[3] <= at(15, 33)


def test_sleeping_household_has_no_events_and_no_left_behind(session):
    seed_places(session)
    zaid = seed_person(session)
    Timeline().stay(["zb", "zk", "zr", "zw"], HOME, at(22, 0, day=-1), at(7, 0), every=20).ingest(
        session
    )
    assert person_events(session, zaid.id) == []
    assert session.query(LeftBehind).count() == 0
    home = session.get(PersonPlaceState, (zaid.id, 1))
    assert home.state == "inside"  # seeded silently, no event (D17)


def test_all_trackers_at_school_is_one_place_and_no_left_behind(session):
    seed_places(session)
    zaid = seed_person(session)
    tl = Timeline()
    overnight(tl, ["zb", "zk", "zr", "zw"], end=at(7, 40))
    tl.walk(["zb", "zk", "zr", "zw"], HOME, SCHOOL, at(7, 40), at(8, 10))
    tl.stay(["zb", "zk", "zr", "zw"], SCHOOL, at(8, 30), at(12, 0))
    tl.ingest(session)
    assert [(t, p) for t, p, _ in person_events(session, zaid.id)] == [
        ("EXIT", "Home"),
        ("ENTER", "School"),
    ]
    assert session.query(LeftBehind).count() == 0


def test_jitter_at_the_edge_of_home_gives_no_person_events(session):
    """40 fixes alternating across Home's edge (the D17 fixture) move nothing."""
    seed_places(session)
    zaid = seed_person(session)
    tl = Timeline()
    overnight(tl, ["zb", "zk", "zr", "zw"], end=at(7, 0))
    inside, edge = (HOME[0] + 0.0005, HOME[1]), (HOME[0] + 0.0020, HOME[1])  # 55 m / 220 m
    for k in range(40):
        tl.add("zr", inside if k % 2 else edge, at(7, 10) + (k + 1) * (at(0, 3) - at(0, 0)))
    tl.ingest(session)
    assert person_events(session, zaid.id) == []


def test_a_late_older_report_never_moves_person_state(session):
    seed_places(session)
    zaid = seed_person(session)
    tl = Timeline()
    overnight(tl, ["zb", "zk", "zr", "zw"], end=at(9, 0))
    tl.ingest(session)
    before = person_events(session, zaid.id)
    # A report from 03:00 at Grandma's arrives late, after the 09:00 fixes.
    Timeline().add("zr", GRANDMA, at(3, 0)).add("zb", GRANDMA, at(3, 1)).ingest(session)
    assert person_events(session, zaid.id) == before
    assert session.get(PersonPlaceState, (zaid.id, 1)).state == "inside"


def test_two_people_arriving_together_get_one_event_each(session):
    seed_places(session)
    zaid = seed_person(session)
    amirah = seed_person(session, "Amirah", {"am": "Amirah"})
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw", "am"], end=at(9, 0))
    tl.walk(["zr", "zb", "zk", "zw", "am"], HOME, GRANDMA, at(9, 0), at(9, 40))
    tl.ingest(session)
    for person in (zaid, amirah):
        assert [(t, p) for t, p, _ in person_events(session, person.id)] == [
            ("EXIT", "Home"),
            ("ENTER", "Grandma's"),
        ]

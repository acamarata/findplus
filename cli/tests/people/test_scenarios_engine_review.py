"""Person engine regressions from the 1.1.6 review (false or missing arrive/leave).

Each test is one reviewed timeline fed through the real ingest -> quality ->
geofence -> person hook chain. A wrong "left School" or a missing "arrived
Home" is what a parent sees, so every case pins the exact events.
"""

from __future__ import annotations

from findplus.db.models import Group
from findplus.people.inputs import infer_person

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


def _now(session, group, when):
    fix, _, _ = infer_person(session, session.get(Group, group.id), when)
    return fix


def test_parked_trackers_never_claim_the_person_when_the_carried_one_goes_quiet(session):
    """Sam walks to School with one pair of shoes, which stop reporting at 9:00.
    The bag, bike and other shoes keep reporting from Home: they never moved,
    so they must not bring Sam home or take him out of School."""
    seed_places(session)
    sam = seed_person(session)
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(7, 40))
    tl.walk(["zr"], HOME, SCHOOL, at(7, 40), at(8, 10))
    tl.stay(["zr"], SCHOOL, at(8, 15), at(9, 0), every=15)
    tl.stay(["zb", "zk", "zw"], HOME, at(8, 0), at(13, 0), every=20)
    tl.ingest(session)
    assert [(e, p) for e, p, _ in person_events(session, sam.id)] == [
        ("EXIT", "Home"),
        ("ENTER", "School"),
    ]
    fix = _now(session, sam, at(11, 0))
    assert not (fix.confidence in ("likely", "probably") and fix.place_name == "Home")
    assert "zr" in fix.stale


def test_a_sleeping_household_still_reads_as_home(session):
    """Everything parked at Home and nothing elsewhere: Home stays the answer."""
    seed_places(session)
    sam = seed_person(session)
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(7, 0))
    tl.ingest(session)
    fix = _now(session, sam, at(7, 0))
    assert fix.confidence in ("likely", "probably") and fix.place_name == "Home"
    assert person_events(session, sam.id) == []


def test_the_quiet_shoes_reporting_again_from_home_bring_sam_home(session):
    """The hold ends when the carried tracker is seen again: it moved, so it counts."""
    seed_places(session)
    sam = seed_person(session)
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(7, 40))
    tl.walk(["zr"], HOME, SCHOOL, at(7, 40), at(8, 10))
    tl.stay(["zr"], SCHOOL, at(8, 15), at(9, 0), every=15)
    tl.stay(["zb", "zk", "zw"], HOME, at(8, 0), at(16, 0), every=20)
    tl.add("zr", HOME, at(15, 40)).add("zr", HOME, at(15, 50))
    tl.ingest(session)
    events = person_events(session, sam.id)
    assert [(e, p) for e, p, _ in events[:2]] == [("EXIT", "Home"), ("ENTER", "School")]
    assert sorted(events[2:]) == [("ENTER", "Home", at(15, 40)), ("EXIT", "School", at(15, 40))]


def _school_morning(tl: Timeline, until=(15, 0)) -> Timeline:
    """Shoes and bag to School at 7:40 to 8:10; bike and white shoes stay home."""
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(7, 40))
    tl.walk(["zr", "zb"], HOME, SCHOOL, at(7, 40), at(8, 10))
    tl.stay(["zr", "zb"], SCHOOL, at(8, 20), at(*until), every=10)
    tl.stay(["zk", "zw"], HOME, at(8, 0), at(*until), every=30)
    return tl


def test_one_stray_fix_never_skips_the_two_exit_confirmation(session):
    """One shoes fix 450 m north of School at 11:05 (accuracy 50 m, not flagged).
    The device geofence rightly waits for a second outside fix; so must Sam."""
    seed_places(session)
    sam = seed_person(session)
    tl = _school_morning(Timeline())
    tl.add("zr", (SCHOOL[0] + 0.00405, SCHOOL[1]), at(11, 5), acc=50.0)
    tl.ingest(session)
    assert [(e, p) for e, p, _ in person_events(session, sam.id)] == [
        ("EXIT", "Home"),
        ("ENTER", "School"),
    ]


def _back_home_then_grandma(tl: Timeline, every_at_grandma=10, walk_every=5) -> Timeline:
    """A school day home at 15:30, then at 16:30 Sam walks to Grandma's with the
    red shoes only. The bag he carried all day stays home."""
    _school_morning(tl, until=(14, 50))
    tl.walk(["zr", "zb"], SCHOOL, HOME, at(15, 0), at(15, 30))
    tl.stay(["zr", "zb"], HOME, at(15, 35), at(16, 30), every=10)
    tl.stay(["zk", "zw"], HOME, at(15, 0), at(19, 0), every=30)
    tl.stay(["zb"], HOME, at(16, 40), at(19, 0), every=10)
    tl.walk(["zr"], HOME, GRANDMA, at(16, 30), at(17, 0), every=walk_every)
    tl.stay(["zr"], GRANDMA, at(17, 0) + (at(0, every_at_grandma) - at(0)), at(19, 0),
            every=every_at_grandma)  # fmt: skip
    return tl


def test_leaving_with_some_trackers_after_a_trip_still_alerts(session):
    """The bag moved this afternoon but has sat at Home for an hour: it no
    longer counts as carried, so the shoes leaving decide it."""
    seed_places(session)
    sam = seed_person(session)
    _back_home_then_grandma(Timeline()).ingest(session)
    tail = [(e, p) for e, p, _ in person_events(session, sam.id)][-2:]
    assert tail == [("EXIT", "Home"), ("ENTER", "Grandma's")]


def test_grandmas_arrival_with_sparse_reports(session):
    seed_places(session)
    sam = seed_person(session)
    _back_home_then_grandma(Timeline(), every_at_grandma=75, walk_every=15).ingest(session)
    tail = [(e, p) for e, p, _ in person_events(session, sam.id)][-2:]
    assert tail == [("EXIT", "Home"), ("ENTER", "Grandma's")]

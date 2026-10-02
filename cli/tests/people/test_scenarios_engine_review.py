"""Person engine regressions from the 1.1.6 review (false or missing arrive/leave).

Each test is one reviewed timeline fed through the real ingest -> quality ->
geofence -> person hook chain. A wrong "left School" or a missing "arrived
Home" is what a parent sees, so every case pins the exact events.
"""

from __future__ import annotations

from findplus.db.models import Group
from findplus.people.inputs import infer_person

from ._helpers import HOME, SCHOOL, Timeline, at, overnight, person_events, seed_person, seed_places


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

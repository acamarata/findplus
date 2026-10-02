"""A person with several carried trackers leaves Home, then arrives at School (uat116 #2).

Three trackers are carried together and report at the same instants; a fourth
stays at Home. The person must leave Home before arriving at School, with the
real crossing times, and must never be "inside" both places at once.
"""

from __future__ import annotations

from sqlalchemy import select

from findplus.db.models import Place
from findplus.db.models_people import PersonPlaceState

from ._helpers import HOME, SCHOOL, Timeline, at, overnight, person_events, seed_person, seed_places

CARRIED = ["zb", "zk", "zr"]


def _midway():
    return ((HOME[0] + SCHOOL[0]) / 2, (HOME[1] + SCHOOL[1]) / 2)


def _morning(session):
    seed_places(session)
    sam = seed_person(session)
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(7, 0))
    for d in CARRIED:
        tl.add(d, HOME, at(7, 15)).add(d, _midway(), at(7, 28)).add(d, SCHOOL, at(7, 37))
    tl.add("zw", HOME, at(7, 30))
    tl.ingest(session)
    return sam


def _inside(session, group_id) -> set[str]:
    rows = session.execute(
        select(Place.name)
        .join(PersonPlaceState, PersonPlaceState.place_id == Place.id)
        .where(PersonPlaceState.group_id == group_id, PersonPlaceState.state == "inside")
    ).all()
    return {r[0] for r in rows}


def test_carried_trackers_reporting_together_leave_home_then_arrive(session):
    sam = _morning(session)
    events = person_events(session, sam.id)
    assert [(e, p) for e, p, _ in events] == [("EXIT", "Home"), ("ENTER", "School")]
    left, arrived = events[0][2], events[1][2]
    assert left <= arrived
    assert at(7, 15) < left <= at(7, 28)
    assert arrived == at(7, 37)


def test_the_person_is_never_inside_two_separate_places(session):
    sam = _morning(session)
    assert _inside(session, sam.id) == {"School"}

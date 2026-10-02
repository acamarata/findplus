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

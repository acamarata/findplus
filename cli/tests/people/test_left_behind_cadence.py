"""Left-behind at real Find Hub cadence: a bag seen every two hours (uat116 #5).

Sam's bag stays at School; it reports at 15:20, 17:10 and 19:05, about every
two hours, the way a quiet tag really does. Sam's shoes and bike are home at
15:33, then one of them reports just after each bag report goes stale. With a
90-minute stale window and two newer sightings needed inside it, the episode
was never confirmed. It must be confirmed on the bag's last fresh sighting
plus a later sighting of Sam.
"""

from __future__ import annotations

from findplus.db.models_people import LeftBehind

from ._helpers import HOME, SCHOOL, Timeline, at, overnight, seed_person, seed_places

CARRIED = ["zr", "zb", "zk"]


def _sparse_school_day(tl: Timeline) -> Timeline:
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(7, 40))
    mid = ((HOME[0] + SCHOOL[0]) / 2, HOME[1])
    for d in CARRIED:
        tl.add(d, HOME, at(7, 40)).add(d, mid, at(7, 55)).add(d, SCHOOL, at(8, 10))
        tl.add(d, SCHOOL, at(11, 5)).add(d, SCHOOL, at(13, 40))
    for d in ("zr", "zk"):
        tl.add(d, SCHOOL, at(15, 0)).add(d, mid, at(15, 16)).add(d, HOME, at(15, 33))
    # Home is quiet in the evening: one sighting of Sam just after each bag
    # report has gone stale (more than 90 minutes old).
    tl.add("zr", HOME, at(16, 55)).add("zk", HOME, at(18, 45)).add("zr", HOME, at(20, 35))
    for when in (at(15, 20), at(17, 10), at(19, 5)):
        tl.add("zb", SCHOOL, when)
    return tl


def test_a_bag_reporting_every_two_hours_is_still_confirmed_left_at_school(session):
    places = seed_places(session)
    seed_person(session)
    _sparse_school_day(Timeline()).ingest(session)
    rows = session.query(LeftBehind).filter_by(device_id="zb", place_id=places["School"].id).all()
    debug = [(r.state, r.clear_reason, r.started_observed_at, r.confirmed_at, r.cleared_at)
             for r in rows]  # fmt: skip
    assert len(rows) == 1, debug
    assert rows[0].confirmed_at is not None, debug
    assert at(15, 40) <= rows[0].confirmed_at <= at(17, 15), debug
    # The bag's last report is 19:05; by 20:40 it is no recent sighting, never "still left".
    assert rows[0].state in ("left_behind", "cleared"), debug

"""Left-behind scenarios (spec § 4 and § 11): the owner's example and its false positives."""

from __future__ import annotations

from findplus.db.models_people import LeftBehind

from ._helpers import HOME, SCHOOL, Timeline, at, overnight, person_events, seed_person, seed_places


def _bag_stays_at_school(tl: Timeline) -> Timeline:
    """Shoes and bag go to school; at 15:00 only the shoes come home."""
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(7, 40))
    tl.walk(["zr", "zb"], HOME, SCHOOL, at(7, 40), at(8, 10))
    tl.stay(["zr", "zb"], SCHOOL, at(8, 30), at(15, 0))
    tl.walk(["zr"], SCHOOL, HOME, at(15, 0), at(15, 30))
    tl.stay(["zr"], HOME, at(15, 33), at(18, 0))
    tl.stay(["zb"], SCHOOL, at(15, 20), at(18, 0))
    tl.stay(["zk", "zw"], HOME, at(8, 0), at(18, 0), every=30)
    return tl


def _school_episodes(session, place_id=2):
    return session.query(LeftBehind).filter_by(device_id="zb", place_id=place_id).all()


def test_owner_example_shoes_leave_bag_stays_at_school(session):
    places = seed_places(session)
    seed_person(session)
    _bag_stays_at_school(Timeline()).ingest(session)
    episodes = _school_episodes(session, places["School"].id)
    assert len(episodes) == 1
    row = episodes[0]
    assert row.state == "left_behind"
    assert at(15, 20) <= row.confirmed_at <= at(15, 40)
    assert row.cleared_at is None


def test_the_person_leaving_school_says_the_bag_stayed(session):
    seed_places(session)
    zaid = seed_person(session)
    _bag_stays_at_school(Timeline()).ingest(session)
    from findplus.db.models import GroupPlaceEvent

    exit_school = (
        session.query(GroupPlaceEvent).filter_by(group_id=zaid.id, place_id=2, event_type="EXIT")
    ).one()
    assert exit_school.note == "Zaid's bag stayed at School."
    assert exit_school.lead_device_id == "zr"


def test_left_behind_clears_next_morning_when_the_bag_moves(session):
    places = seed_places(session)
    seed_person(session)
    tl = _bag_stays_at_school(Timeline())
    tl.stay(["zb"], SCHOOL, at(18, 20), at(7, 0, day=1), every=60)
    tl.stay(["zr", "zk", "zw"], HOME, at(18, 30), at(7, 0, day=1), every=60)
    tl.walk(["zb"], SCHOOL, HOME, at(7, 0, day=1), at(7, 30, day=1))
    tl.ingest(session)
    row = _school_episodes(session, places["School"].id)[0]
    assert row.state == "cleared"
    assert row.clear_reason in ("carried", "rejoined")
    assert row.cleared_at >= at(7, 0, day=1)


def test_second_pair_of_shoes_left_at_home_is_an_episode_at_home(session):
    """White shoes stay home every day: tracked as an episode, but at a Home place,
    where alerts are off (alerts/dispatch_left_behind.py filters kind=home)."""
    places = seed_places(session)
    seed_person(session)
    _bag_stays_at_school(Timeline()).ingest(session)
    white = session.query(LeftBehind).filter_by(device_id="zw").all()
    assert white, "the shoes that stayed home should show as apart (chip only)"
    assert {r.place_id for r in white} == {places["Home"].id}


def test_sibling_carries_the_bag_gives_no_person_exit(session):
    """Only the bag moves: 0.5 x 2 = 1.0 against the parked shoes, shoes and bike;
    `unsure` never moves person state and never opens an episode."""
    seed_places(session)
    zaid = seed_person(session)
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(9, 0))
    tl.walk(["zb"], HOME, SCHOOL, at(9, 0), at(9, 30))
    tl.stay(["zr", "zk", "zw"], HOME, at(9, 5), at(9, 30), every=5)
    tl.ingest(session)
    assert person_events(session, zaid.id) == []
    assert session.query(LeftBehind).filter(LeftBehind.state == "left_behind").count() == 0


def test_dismiss_silences_that_tracker_at_that_place_for_the_day(session):
    from findplus.people.left_behind import dismiss

    places = seed_places(session)
    zaid = seed_person(session)
    _bag_stays_at_school(Timeline()).ingest(session)
    row = _school_episodes(session, places["School"].id)[0]
    dismiss(session, zaid.id, row.id, now=at(18, 5))
    Timeline().stay(["zb"], SCHOOL, at(18, 20), at(19, 0)).stay(
        ["zr"], HOME, at(18, 20), at(19, 0)
    ).ingest(session)
    rows = _school_episodes(session, places["School"].id)
    assert [r.clear_reason for r in rows] == ["dismissed"]

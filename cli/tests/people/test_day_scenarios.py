"""Daily summary over named synthetic days (spec § 11, package C).

Every scenario feeds each tracker's sightings through the real ingest, geofence
and person-event chain, then asks the real loader and algorithm for the day.
"""

from __future__ import annotations

from findplus.people.day_load import day_payload

from ._day_helpers import ALL, DAY, UTC_TZ, school_day, summary, texts
from ._helpers import GRANDMA, HOME, SCHOOL, Timeline, at, seed_person, seed_places

SCHOOL_DAY = [
    "Overnight at Home",
    "7:40 AM left Home",
    "8:10 AM arrived at School",
    "3:00 PM left School",
    "At Home from 3:33 PM",
]


def test_school_day_reads_like_the_owner_sample(session):
    seed_places(session)
    sam = seed_person(session)
    school_day(Timeline()).ingest(session)
    payload = summary(session, sam)
    assert texts(payload) == SCHOOL_DAY
    assert [x["kind"] for x in payload["lines"]] == [
        "overnight", "left", "arrived", "left", "at_home_from",
    ]  # fmt: skip
    assert not any(x["approximate"] for x in payload["lines"])
    assert payload["person"] == {"id": sam.id, "name": "Sam"}
    assert payload["heading"] == "Sam's day" and payload["empty"] is False


def test_every_line_names_the_trackers_behind_it(session):
    seed_places(session)
    sam = seed_person(session)
    school_day(Timeline()).ingest(session)
    lines = summary(session, sam)["lines"]
    for line in lines[1:]:
        assert line["evidence"] and line["via"]
        assert set(line["evidence"]) <= {"zr", "zb"}  # the carried trackers, never the parked
        assert line["confidence"] in ("high", "medium")
    assert lines[1]["place_name"] == "Home" and lines[2]["place_name"] == "School"
    assert lines[1]["latitude"] and lines[1]["longitude"]
    assert "just" not in " ".join(texts({"lines": lines})).lower().split()


def test_today_fresh_data_says_still_at_but_not_twice_for_home(session):
    seed_places(session)
    sam = seed_person(session)
    tl = Timeline().stay(ALL, HOME, at(0, 0), at(6, 0), every=5)
    tl.walk(["zr", "zb"], HOME, SCHOOL, at(6, 5), at(6, 40), every=5)
    tl.stay(["zr", "zb"], SCHOOL, at(6, 45), at(7, 55), every=5)
    tl.stay(["zk", "zw"], HOME, at(6, 5), at(7, 55), every=5)
    tl.ingest(session)
    payload = summary(session, sam, now=at(8, 0))
    assert texts(payload)[-1] == "Still at School (seen 7:55 AM)"
    assert payload["now"]["place_name"] == "School"
    assert [x["kind"] for x in payload["lines"]][-2:] == ["arrived", "still_at"]


def test_school_day_today_ends_with_one_home_line(session):
    seed_places(session)
    sam = seed_person(session)
    school_day(Timeline()).ingest(session)
    payload = summary(session, sam, now=at(17, 5))
    assert texts(payload) == SCHOOL_DAY  # "At Home from" already says it; no second line


def test_stale_data_never_says_still_at(session):
    seed_places(session)
    sam = seed_person(session)
    school_day(Timeline()).ingest(session)
    payload = summary(session, sam, now=at(21, 0))
    last = texts(payload)[-1]
    assert last == "Last seen near Home at 5:00 PM; nothing since"
    assert "Still at" not in " ".join(texts(payload))
    assert (
        payload["lines"][-1]["kind"] == "last_seen" and payload["lines"][-1]["confidence"] == "low"
    )


def test_sick_day_at_home(session):
    seed_places(session)
    sam = seed_person(session)
    Timeline().stay(ALL, HOME, at(0, 0), at(21, 40), every=20).ingest(session)
    past = summary(session, sam)
    assert texts(past) == ["Overnight at Home", "Seen at Home through 9:40 PM"]
    today = summary(session, sam, now=at(14, 5))
    assert texts(today) == ["Overnight at Home", "Still at Home (seen 2:00 PM)"]
    assert past["gaps"] == []  # fixes at Home never make a gap


def test_trip_to_grandmas_and_an_unnamed_stop(session):
    seed_places(session)
    sam = seed_person(session)
    stop = (HOME[0] + 0.0190, HOME[1])  # about 2.1 km north of Home, not a saved place
    c = ["zr", "zb"]
    tl = Timeline().stay(ALL, HOME, at(0, 0), at(9, 55), every=5)
    tl.walk(c, HOME, stop, at(9, 55), at(10, 5), every=5)
    tl.stay(c, stop, at(10, 5), at(10, 45), every=5)
    tl.walk(c, stop, GRANDMA, at(10, 45), at(11, 25), every=5)
    tl.stay(c, GRANDMA, at(11, 30), at(14, 30), every=5)
    tl.walk(c, GRANDMA, HOME, at(14, 30), at(15, 10), every=5)
    tl.stay(c, HOME, at(15, 15), at(16, 0), every=5)
    tl.stay(["zk", "zw"], HOME, at(10, 0), at(16, 0), every=5)
    tl.ingest(session)
    got = texts(summary(session, sam))
    assert got[0] == "Overnight at Home"
    assert "10:00 AM left Home" in got
    assert any(x.endswith("arrived at Grandma's") for x in got)
    assert any(x.endswith("left Grandma's") for x in got)
    assert got[-1].startswith("At Home from ")
    stay = next(x for x in got if " at an unnamed spot, " in x)
    assert stay == "10:05 to 10:45 AM at an unnamed spot, 2.1 km from Home"


def test_bag_left_at_school_day(session):
    seed_places(session)
    sam = seed_person(session)
    tl = Timeline().stay(ALL, HOME, at(0, 0), at(7, 35), every=5)
    tl.walk(["zr", "zb"], HOME, SCHOOL, at(7, 35), at(8, 10), every=5)
    tl.stay(["zr", "zb"], SCHOOL, at(8, 15), at(14, 55), every=5)
    tl.walk(["zr"], SCHOOL, HOME, at(14, 55), at(15, 30), every=5)
    tl.stay(["zr"], HOME, at(15, 33), at(18, 0), every=5)
    tl.stay(["zb"], SCHOOL, at(15, 0), at(18, 0), every=20)
    tl.stay(["zk", "zw"], HOME, at(7, 40), at(18, 0), every=20)
    tl.ingest(session)
    payload = summary(session, sam)
    got = texts(payload)
    assert "Bag stayed at School from 3:00 PM." in got
    assert len(payload["left_behind"]) == 1
    episode = payload["left_behind"][0]
    assert episode["device_id"] == "zb" and episode["place_name"] == "School"
    line = next(x for x in payload["lines"] if x["kind"] == "left_behind")
    assert line["evidence"] == ["zb"] and line["via"] == "bag"
    assert got.index("3:00 PM left School") <= got.index(line["text"])
    # The bag's parked sightings never make the person look "seen" at School all evening.
    assert not any(x.startswith("Still at School") for x in got)


def test_multi_tracker_disagreement_cites_only_the_supporters(session):
    seed_places(session)
    sam = seed_person(session)
    tl = Timeline().stay(ALL, HOME, at(0, 0), at(9, 0), every=5)
    tl.walk(["zr", "zk"], HOME, SCHOOL, at(9, 0), at(9, 30), every=5)
    tl.stay(["zr", "zk"], SCHOOL, at(9, 35), at(12, 0), every=5)
    tl.walk(["zb"], HOME, GRANDMA, at(9, 0), at(10, 0), every=5)  # the bag goes elsewhere
    tl.stay(["zb"], GRANDMA, at(10, 5), at(12, 0), every=5)
    tl.stay(["zw"], HOME, at(9, 5), at(12, 0), every=20)
    tl.ingest(session)
    payload = summary(session, sam)
    arrived = [x for x in payload["lines"] if x["kind"] == "arrived"]
    assert [x["place_name"] for x in arrived] == ["School"]
    assert "zb" not in arrived[0]["evidence"]
    # The bag is not the person: it shows up as left behind, never as an arrival there.
    assert texts(payload)[-1] == "Bag stayed at Grandma's from 10:05 AM."
    assert not any("arrived at Grandma" in t for t in texts(payload))


def test_two_days_in_a_row_start_where_the_first_ended(session):
    seed_places(session)
    sam = seed_person(session)
    school_day(Timeline()).ingest(session)
    Timeline().stay(ALL, HOME, at(17, 5), at(7, 0, day=1), every=30).ingest(session)
    one = summary(session, sam)
    two = summary(session, sam, day=DAY.replace(day=22))
    assert texts(one) == SCHOOL_DAY
    assert texts(two) == ["Overnight at Home", "Seen at Home through 6:35 AM"]
    assert one["date"] == "2026-09-21" and two["date"] == "2026-09-22"


def test_a_day_with_no_sightings_is_empty(session):
    seed_places(session)
    sam = seed_person(session)
    payload = summary(session, sam)
    assert payload["lines"] == [] and payload["empty"] is True
    assert payload["suspect_count"] == 0 and payload["gaps"] == []
    assert payload["label"].startswith("Stays and trips are worked out")


def test_first_sighting_late_reads_no_sightings_until(session):
    seed_places(session)
    sam = seed_person(session)
    Timeline().stay(["zr"], SCHOOL, at(7, 12), at(9, 0), every=20).ingest(session)
    got = texts(summary(session, sam))
    assert got[0] == "No sightings until 7:12 AM"


def test_a_long_gap_away_from_home_is_named(session):
    seed_places(session)
    sam = seed_person(session)
    tl = Timeline().stay(["zr"], SCHOOL, at(8, 0), at(11, 0), every=20)
    tl.stay(["zr"], SCHOOL, at(13, 0), at(14, 0), every=20)
    tl.ingest(session)
    payload = summary(session, sam)
    assert "No sightings 11:00 AM to 1:00 PM." in texts(payload)
    assert payload["gaps"][0]["minutes"] == 120


def test_summary_is_read_only(session):
    seed_places(session)
    sam = seed_person(session)
    school_day(Timeline()).ingest(session)
    from findplus.db.models import LocationObservation

    before = session.query(LocationObservation).count()
    day_payload(session, sam, DAY, UTC_TZ, at(6, 0, day=1))
    assert session.query(LocationObservation).count() == before

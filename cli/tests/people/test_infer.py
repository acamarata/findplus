"""people/infer.py and people/describe.py: the pure "where is Sam now" engine (spec § 3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from findplus.people.describe import now_text
from findplus.people.infer import InferParams, MemberIn, PlaceRef, TrackerFix, infer, motion_of
from findplus.people.inputs import Tracker

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
HOME = (41.10, -80.64)
SCHOOL = (41.127, -80.64)
PLACES = [
    PlaceRef(1, "Home", "home", round(HOME[0] * 1e7), round(HOME[1] * 1e7), 150),
    PlaceRef(2, "School", "school", round(SCHOOL[0] * 1e7), round(SCHOOL[1] * 1e7), 150),
]


def _fix(where, minutes_ago, i=0, acc=30.0):
    when = NOW - timedelta(minutes=minutes_ago)
    return TrackerFix(i, round(where[0] * 1e7), round(where[1] * 1e7), acc, when, when)


def parked(where, last_ago=5):
    """Still for seven hours, last seen `last_ago` minutes ago."""
    return (_fix(where, 420), _fix(where, 200), _fix(where, last_ago))


def carried(frm, to, last_ago=5):
    return (_fix(frm, 120), _fix(to, last_ago + 10), _fix(to, last_ago))


def member(device_id, role, weight, fixes, inside=()):
    return MemberIn(device_id, device_id, role, weight, fixes, tuple(inside))


def test_parked_moved_and_unknown_motion():
    p = InferParams()
    assert motion_of(parked(HOME), NOW, p) == "parked"
    assert motion_of(carried(HOME, SCHOOL), NOW, p) == "carried"
    assert motion_of((_fix(HOME, 30),), NOW, p) == "unknown"


def test_worked_example_shoes_leave_bag_bike_white_shoes_stay():
    fix = infer(
        [
            member("red", "shoes", 0.8, carried(HOME, SCHOOL), inside=[2]),
            member("bag", "bag", 0.5, parked(HOME), inside=[1]),
            member("bike", "bike", 0.4, parked(HOME), inside=[1]),
            member("white", "shoes", 0.8, parked(HOME), inside=[1]),
        ],
        PLACES,
        NOW,
    )
    assert fix.confidence == "likely"
    assert fix.supporters == ("red",)
    assert fix.place_name == "School" and fix.relation == "at"
    assert fix.best_score / fix.runner_up == pytest.approx(2.35, abs=0.01)


def test_lat_lon_are_the_lead_trackers_own_fix_never_an_average():
    red, bag = carried(HOME, SCHOOL), carried(HOME, (SCHOOL[0] + 0.0005, SCHOOL[1]))
    fix = infer([member("red", "shoes", 0.8, red), member("bag", "bag", 0.5, bag)], PLACES, NOW)
    assert (fix.lat, fix.lon) == (red[-1].lat, red[-1].lon)


def test_sibling_carrying_the_bag_is_unsure_and_names_both_sides():
    members = [
        member("bag", "bag", 0.5, carried(HOME, SCHOOL)),
        member("red", "shoes", 0.8, parked(HOME)),
        member("white", "shoes", 0.8, parked(HOME)),
        member("bike", "bike", 0.4, parked(HOME)),
    ]
    fix = infer(members, PLACES, NOW)
    assert fix.confidence == "unsure"
    trackers = [Tracker(m.device_id, m.device_id, m.role, "name", None, m.weight) for m in members]
    text = now_text(fix, trackers, PLACES, NOW)
    assert text.startswith("Not sure: ")
    assert "School" in text and "Home" in text


def test_known_limit_a_sibling_wearing_sams_shoes_reads_as_sam():
    """Spec § 13: nothing in this data can tell; the alert names its tracker instead."""
    fix = infer(
        [
            member("red", "shoes", 0.8, carried(HOME, SCHOOL)),
            member("bag", "bag", 0.5, parked(HOME)),
        ],
        PLACES,
        NOW,
    )
    assert fix.confidence == "likely" and fix.lead_device_id == "red"


def test_phone_dies_watch_still_places_the_person_and_the_text_names_the_phone():
    members = [
        member("phone", "phone", 1.0, (_fix(SCHOOL, 400), _fix(SCHOOL, 300))),
        member("watch", "watch", 1.0, (_fix(SCHOOL, 30), _fix(SCHOOL, 10))),
    ]
    fix = infer(members, PLACES, NOW)
    assert fix.stale == ("phone",)
    assert fix.supporters == ("watch",)
    trackers = [Tracker(m.device_id, m.device_id, m.role, "name", None, m.weight) for m in members]
    assert "No recent sighting from phone." in now_text(fix, trackers, PLACES, NOW)


def test_stale_data_never_claims_certainty():
    members = [member("bag", "bag", 0.5, (_fix(HOME, 300),), inside=[1])]
    fix = infer(members, PLACES, NOW)
    assert fix.confidence == "unknown"
    assert fix.lat is None and fix.relation == "near"
    trackers = [Tracker("bag", "Sam Bag", "bag", "name", None, 0.5)]
    text = now_text(fix, trackers, PLACES, NOW)
    assert text.startswith("No recent sightings. Last seen near Home at ")
    assert "Likely" not in text and " is at " not in text


def test_only_the_bag_reporting_is_probably_not_likely():
    fix = infer([member("bag", "bag", 0.5, (_fix(HOME, 20), _fix(HOME, 5)))], PLACES, NOW)
    assert fix.confidence == "probably"


def test_nobody_ever_seen_is_unknown_with_no_place():
    fix = infer([member("bag", "bag", 0.5, ())], PLACES, NOW)
    assert fix.confidence == "unknown" and fix.observed_at is None
    assert now_text(fix, [], PLACES, NOW) == "No recent sightings."


def test_unnamed_spot_is_measured_from_home():
    far = (41.20, -80.64)  # ~11 km north of Home
    fix = infer([member("w", "watch", 1.0, carried(HOME, far))], PLACES, NOW)
    assert fix.relation == "spot" and fix.reference_place == "Home"
    trackers = [Tracker("w", "Sam Watch", "watch", "name", None, 1.0)]
    assert "an unnamed spot, 11.1 km from Home" in now_text(fix, trackers, PLACES, NOW)


def test_naive_now_is_refused():
    with pytest.raises(ValueError):
        infer([], PLACES, datetime(2026, 9, 21, 12, 0))

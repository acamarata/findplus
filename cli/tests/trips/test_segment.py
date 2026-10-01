"""Segmentation of synthetic days into stays, trips and gaps."""

from __future__ import annotations

from findplus.trips.segment import SegmentParams, segment
from tests.trips._synth import HOME, SCHOOL, SHOP, Day, hm, home_lookup, offset


def test_device_with_no_fixes_is_empty() -> None:
    seg = segment([])
    assert (seg.stays, seg.trips, seg.gaps, seg.dropped, seg.fix_count) == ([], [], [], [], 0)


def test_home_all_day_with_jitter_is_one_stay_and_no_trips() -> None:
    day = Day()
    day.stay(0, 23 * 60 + 50, HOME, every=15, acc=80.0, jitter_m=45.0)
    seg = segment(day.fixes, lookup=home_lookup)
    assert len(seg.stays) == 1 and seg.trips == []
    stay = seg.stays[0]
    assert stay.label == "Home" and stay.fix_count == len(day.fixes)
    assert stay.duration_min > 23 * 60


def test_repeated_identical_fixes_collapse_to_one_row_with_a_count() -> None:
    day = Day()
    for minute in range(0, 120, 5):
        day.at(minute, HOME, acc=30.0)  # 0 m from the previous fix, every time
    seg = segment(day.fixes)
    assert len(seg.stays) == 1 and seg.stays[0].fix_count == 24
    assert seg.stays[0].label == "Unnamed stop"


def test_jitter_wider_than_the_floor_but_inside_the_accuracy_circle_is_not_a_trip() -> None:
    day = Day()
    day.stay(0, 60, HOME, every=10, acc=200.0)
    day.at(65, offset(HOME, 250, 0), acc=200.0)  # 250 m away, accuracy 200 m: same place
    day.stay(70, 120, HOME, every=10, acc=200.0)
    seg = segment(day.fixes)
    assert len(seg.stays) == 1 and seg.trips == []


def test_a_short_wobble_between_two_home_stays_never_creates_a_trip() -> None:
    day = Day()
    day.stay(0, 60, HOME, every=10, acc=20.0)
    day.at(65, offset(HOME, 120, 0), acc=20.0)  # outside 75 m, a one-fix wobble
    day.stay(70, 130, HOME, every=10, acc=20.0)
    seg = segment(day.fixes, lookup=home_lookup)
    assert len(seg.stays) == 1 and seg.trips == []
    assert seg.stays[0].fix_count == len(day.fixes)


def test_school_run_gives_three_stays_and_two_trips_with_place_labels() -> None:
    day = Day()
    day.stay(0, 7 * 60, HOME, every=20, acc=60.0, jitter_m=30.0)  # 00:00-07:00 home
    day.at(7 * 60 + 40, offset(HOME, 1400, 1000), acc=100.0)  # on the way
    day.stay(8 * 60 + 5, 15 * 60, SCHOOL, every=30, acc=60.0, jitter_m=30.0)
    day.at(15 * 60 + 25, offset(HOME, 1400, 1000), acc=100.0)
    day.stay(15 * 60 + 50, 23 * 60, HOME, every=30, acc=60.0, jitter_m=30.0)
    seg = segment(day.fixes, lookup=home_lookup)
    assert [s.label for s in seg.stays] == ["Home", "School", "Home"]
    assert len(seg.trips) == 2
    out, back = seg.trips
    assert (out.from_stay, out.to_stay) == ("s0", "s1")
    assert (back.from_stay, back.to_stay) == ("s1", "s2")
    assert hm(out.start) == "07:00" and hm(out.end) == "08:05"
    assert out.fix_count == 1 and 2000 < out.distance_m < 4500
    assert out.longest_gap_min >= 40


def test_two_trips_with_an_unnamed_stop_between() -> None:
    day = Day()
    day.stay(0, 30, HOME, every=10)
    day.at(40, offset(HOME, 400, -1500))
    day.stay(50, 90, SHOP, every=10)
    day.at(100, offset(SHOP, -800, 3000))
    day.stay(110, 150, SCHOOL, every=10)
    seg = segment(day.fixes, lookup=home_lookup)
    assert [s.label for s in seg.stays] == ["Home", "Unnamed stop", "School"]
    assert len(seg.trips) == 2 and all(t.fix_count == 1 for t in seg.trips)


def test_a_single_impossible_fix_is_dropped_from_trips_but_reported() -> None:
    day = Day()
    day.stay(0, 40, HOME, every=5)
    stray = day.at(42, offset(HOME, 60_000, 0))  # 60 km in two minutes
    day.stay(44, 90, HOME, every=5)
    seg = segment(day.fixes, lookup=home_lookup)
    assert seg.trips == [] and len(seg.stays) == 1
    assert [f.id for f in seg.dropped] == [stray.id]
    assert seg.fix_count == len(day.fixes)  # raw count still includes it


def test_a_real_slow_excursion_with_one_fix_is_kept_as_a_trip() -> None:
    day = Day()
    day.stay(0, 30, HOME, every=10)
    day.at(90, offset(HOME, 0, 2500))  # 2.5 km, 60 minutes each way: plausible
    day.stay(180, 220, HOME, every=10)
    seg = segment(day.fixes, lookup=home_lookup)
    assert seg.dropped == []
    assert len(seg.stays) == 2 and len(seg.trips) == 1


def test_a_stray_first_fix_is_dropped() -> None:
    day = Day()
    day.at(0, offset(HOME, 80_000, 0))
    day.stay(2, 60, HOME, every=5)
    seg = segment(day.fixes)
    assert len(seg.dropped) == 1 and seg.trips == [] and len(seg.stays) == 1


def test_sparse_fixes_become_one_trip_and_honest_gap_markers() -> None:
    day = Day()
    for i, minute in enumerate((0, 150, 300, 450)):
        day.at(minute, offset(HOME, 0, 5000 * i), acc=150.0)
    seg = segment(day.fixes)
    assert seg.stays == [] and len(seg.trips) == 1
    assert len(seg.gaps) == 3 and all(g.minutes == 150 for g in seg.gaps)
    assert seg.trips[0].fix_count == 4


def test_gap_marker_inside_a_stay_says_no_sightings_between() -> None:
    day = Day()
    day.stay(0, 190, HOME, every=10)  # last fix 03:10
    day.stay(280, 400, HOME, every=10)  # next fix 04:40
    seg = segment(day.fixes)
    assert len(seg.stays) == 1
    (gap,) = seg.gaps
    assert (hm(gap.start), hm(gap.end), gap.inside) == ("03:10", "04:40", "s0")
    assert seg.stays[0].longest_gap_min == 90


def test_gap_threshold_is_a_parameter() -> None:
    day = Day()
    day.stay(0, 30, HOME, every=10)
    day.stay(75, 120, HOME, every=10)
    assert segment(day.fixes).gaps == []
    assert len(segment(day.fixes, SegmentParams(gap_min=30)).gaps) == 1


def test_a_device_that_only_sat_still_briefly_is_reported_as_a_stay() -> None:
    day = Day()
    day.stay(0, 6, HOME, every=2)
    seg = segment(day.fixes)
    assert len(seg.stays) == 1 and seg.trips == []


def test_trip_distance_is_the_sum_of_straight_lines() -> None:
    day = Day()
    day.stay(0, 30, HOME, every=10)
    day.at(40, offset(HOME, 1000, 0))
    day.stay(50, 90, offset(HOME, 2000, 0), every=10)
    seg = segment(day.fixes)
    assert len(seg.trips) == 1
    assert 1900 < seg.trips[0].distance_m < 2100

"""The pure day algorithm (people/day.py) on hand-made inputs: no database."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from findplus.people.day import build_day
from findplus.people.day_text import clock, clock_range, suspect_sentence
from findplus.people.day_types import (
    DayInput,
    EpisodeIn,
    EventIn,
    NowIn,
    PlaceIn,
    TrackerIn,
)
from findplus.quality.fix import Fix

UTC_TZ = ZoneInfo("UTC")
DAY = date(2026, 9, 21)
HOME = PlaceIn(1, "Home", "home", 41.1, -80.64, 150)
SCHOOL = PlaceIn(2, "School", "school", 41.127, -80.64, 150)
TRACKERS = (
    TrackerIn("zr", "Zaid Shoes", "shoes", "shoes", 1.0),
    TrackerIn("zb", "Zaid Bag", "bag", "bag", 0.5),
)
_n = iter(range(1, 10_000))


def t(h: int, m: int = 0, day: int = 0) -> datetime:
    return datetime(2026, 9, 21, tzinfo=UTC) + timedelta(days=day, hours=h, minutes=m)


def fix(place: PlaceIn, when: datetime, acc: float = 30.0) -> Fix:
    return Fix(next(_n), when, place.lat, place.lon, acc)


def every(place: PlaceIn, a: datetime, b: datetime, minutes: int = 10) -> list[Fix]:
    out, cur = [], a
    while cur <= b:
        out.append(fix(place, cur))
        cur += timedelta(minutes=minutes)
    return out


def day_input(fixes: dict, **kw) -> DayInput:
    base = dict(
        name="Zaid", day=DAY, tz=UTC_TZ, now=t(6, 0, day=1), stale_after_minutes=90,
        trackers=TRACKERS, fixes={k: tuple(v) for k, v in fixes.items()}, suspect_count=0,
        events=(), episodes=(), places=(HOME, SCHOOL),
    )  # fmt: skip
    base.update(kw)
    return DayInput(**base)


def texts(inp: DayInput) -> list[str]:
    return [x.text for x in build_day(inp).lines]


def test_clock_and_range_formats():
    assert clock(t(0, 5), UTC_TZ) == "12:05 AM"
    assert clock(t(12, 0), UTC_TZ) == "12:00 PM"
    assert clock(t(15, 3), UTC_TZ) == "3:03 PM"
    assert clock_range(t(10, 5), t(11, 20), UTC_TZ) == "10:05 to 11:20 AM"
    assert clock_range(t(11, 30), t(13, 10), UTC_TZ) == "11:30 AM to 1:10 PM"
    assert clock(t(23, 30), ZoneInfo("America/New_York")) == "7:30 PM"


def test_suspect_sentence_counts():
    assert suspect_sentence(0) is None
    assert suspect_sentence(1) == "1 sighting looked wrong and was left out."
    assert suspect_sentence(2) == "2 sightings looked wrong and were left out."


def test_a_time_is_around_when_the_sighting_before_it_is_over_ten_minutes_back():
    shoes = [*every(HOME, t(0), t(7, 0), 30), *every(SCHOOL, t(8, 0), t(9, 0), 5)]
    ev = EventIn(t(8, 0), "ENTER", 2, "zr", ("zr",), "high")
    line = next(
        x for x in build_day(day_input({"zr": shoes}, events=(ev,))).lines if x.kind == "arrived"
    )
    assert line.approximate and line.text == "around 8:00 AM arrived at School"
    dense = [*every(HOME, t(0), t(7, 55), 5), *every(SCHOOL, t(8, 0), t(9, 0), 5)]
    line = next(
        x for x in build_day(day_input({"zr": dense}, events=(ev,))).lines if x.kind == "arrived"
    )
    assert not line.approximate and line.text == "8:00 AM arrived at School"


def test_only_the_last_home_visit_folds_into_at_home_from():
    shoes = every(HOME, t(0), t(11, 55), 5) + every(HOME, t(12, 0), t(12, 30), 5)
    shoes += every(SCHOOL, t(12, 35), t(15, 30), 5) + every(HOME, t(15, 33), t(17, 0), 5)
    evs = (
        EventIn(t(12, 0), "ENTER", 1, "zr", ("zr",), "high"),
        EventIn(t(12, 35), "EXIT", 1, "zr", ("zr",), "high"),
        EventIn(t(15, 33), "ENTER", 1, "zr", ("zr",), "high"),
    )
    got = texts(day_input({"zr": shoes}, events=evs))
    assert got[1:] == ["12:00 PM arrived at Home", "12:35 PM left Home", "At Home from 3:33 PM"]


def test_lead_never_a_tracker_that_was_left_behind():
    bag = every(SCHOOL, t(8), t(12), 10)
    shoes = every(HOME, t(8), t(12), 10)
    ep = EpisodeIn(1, "zr", 2, "School", t(9), t(9, 20), None, None, 41.127, -80.64)
    inp = day_input({"zr": shoes, "zb": bag}, episodes=(ep,))
    assert build_day(inp).lead_device_id == "zb"


def test_left_behind_at_home_is_not_news_and_away_is():
    ep_home = EpisodeIn(1, "zb", 1, "Home", t(8), t(8, 20), None, None, 41.1, -80.64)
    ep_school = EpisodeIn(
        2, "zb", 2, "School", t(15), t(15, 20), t(7, 50, day=1), "carried", 41.127, -80.64
    )
    shoes = every(HOME, t(0), t(8), 30)
    lines = texts(day_input({"zr": shoes}, episodes=(ep_home, ep_school)))
    assert lines[-1] == "Bag stayed at School from 3:00 PM."
    assert not any("Home from" in x and x.startswith("Bag") for x in lines)
    # A day when it was picked up shows both ends, with the date on an end outside the day.
    day2 = day_input({"zr": shoes}, episodes=(ep_school,), day=date(2026, 9, 22))
    assert (
        build_day(day2).lines[-1].text
        == "Bag stayed at School from Mon Sep 21, 3:00 PM until 7:50 AM."
    )


def test_overnight_needs_a_home_sighting_unless_the_morning_confirms_it():
    sparse = every(HOME, t(0, 0, day=-1) + timedelta(hours=20), t(0), 30)  # last Home fix 00:00
    only_late = every(HOME, t(3, 0), t(9, 0), 60)
    # Sighting at 00:00 exactly: fresh anchor -> high confidence.
    line = build_day(day_input({"zr": [*sparse, *only_late]})).lines[0]
    assert line.text == "Overnight at Home" and line.confidence == "high"
    # Last Home sighting 5 hours before midnight, then Home again at 03:00: bracketed, medium.
    old = every(HOME, t(18, 0, day=-1), t(19, 0, day=-1), 30)
    line = build_day(day_input({"zr": [*old, *only_late]})).lines[0]
    assert line.text == "Overnight at Home" and line.confidence == "medium"
    # No earlier sighting at all: say so, with the first sighting's time.
    line = build_day(day_input({"zr": every(SCHOOL, t(7, 12), t(8, 0))})).lines[0]
    assert line.text == "No sightings until 7:12 AM" and line.kind == "no_sightings"


def _now(**kw) -> NowIn:
    base = {
        "confidence": "likely", "place_id": 2, "place_name": "School", "relation": "at",
        "distance_m": None, "reference_place": None, "observed_at": t(15, 58),
        "lead_device_id": "zr", "supporters": ("zr",), "lat": 41.127, "lon": -80.64,
    }  # fmt: skip
    base.update(kw)
    return NowIn(**base)


def _today(now_fix, now) -> DayInput:
    shoes = every(HOME, t(0), t(7, 30), 30) + every(SCHOOL, t(8), t(15, 58), 10)
    ev = EventIn(t(8), "ENTER", 2, "zr", ("zr",), "high")
    return day_input({"zr": shoes}, events=(ev,), now=now, now_fix=now_fix)


def test_last_line_still_at_only_when_fresh_and_in_a_place():
    assert texts(_today(_now(), t(16, 5)))[-1] == "Still at School (seen 3:58 PM)"
    stale = texts(_today(_now(confidence="unknown"), t(19, 0)))[-1]
    assert stale == "Last seen near School at 3:58 PM; nothing since"
    old_but_confident = texts(_today(_now(), t(19, 0)))[-1]
    assert old_but_confident == "Last seen near School at 3:58 PM; nothing since"
    assert "Still at" not in old_but_confident


def test_last_line_in_an_unnamed_spot_names_the_distance_and_stays_honest():
    spot = _now(
        place_id=None, place_name=None, relation="spot", distance_m=1200.0, reference_place="Home"
    )
    fresh = texts(_today(spot, t(16, 5)))[-1]
    assert fresh == "Last seen at an unnamed spot, 1.2 km from Home at 3:58 PM"
    stale = texts(_today(spot, t(20, 0)))[-1]
    assert stale == "Last seen at an unnamed spot, 1.2 km from Home at 3:58 PM; nothing since"


def test_no_last_line_for_a_past_day_or_a_stale_yesterday_fix():
    past = _today(_now(), t(16, 5)).__class__(
        **{**_today(_now(), t(16, 5)).__dict__, "now": t(6, 0, day=1)}
    )
    assert not any(x.kind in ("still_at", "last_seen") for x in build_day(past).lines)
    yesterday = _today(_now(observed_at=t(22, 0, day=-1)), t(9, 0))
    assert not any(x.kind in ("still_at", "last_seen") for x in build_day(yesterday).lines)


def test_gap_skips_home_to_home_and_names_the_rest():
    shoes = every(HOME, t(0), t(2), 10) + every(HOME, t(5), t(7, 50), 10)  # asleep at Home
    shoes += every(SCHOOL, t(8), t(9), 10) + every(SCHOOL, t(12), t(13), 10)
    result = build_day(day_input({"zr": shoes}))
    assert [(g.start, g.end) for g in result.gaps] == [(t(9), t(12))]
    assert "No sightings 9:00 AM to 12:00 PM." in [x.text for x in result.lines]


def test_the_trackers_left_behind_do_not_hide_a_gap():
    shoes = every(SCHOOL, t(8), t(9), 10) + every(SCHOOL, t(13), t(14), 10)
    bag = every(SCHOOL, t(8), t(14), 10)  # parked all day, reporting
    ep = EpisodeIn(1, "zb", 2, "School", t(9, 10), t(9, 30), None, None, 41.127, -80.64)
    result = build_day(day_input({"zr": shoes, "zb": bag}, episodes=(ep,)))
    assert [g.minutes for g in result.gaps] == [240]


def test_empty_day_and_never_the_word_just():
    result = build_day(day_input({"zr": []}))
    assert result.lines == [] and result.empty
    busy = _today(_now(), t(16, 5))
    assert all("just" not in x.text.lower().split() for x in build_day(busy).lines)

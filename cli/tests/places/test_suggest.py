"""places.suggest: likely places from stays, on three synthetic weeks of a school-run family."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from findplus.geo import haversine_meters
from findplus.places.suggest import MIN_STAY_MIN, find_candidates
from findplus.trips.models import Stay
from findplus.trips.segment import SegmentParams, segment
from tests.places._family import GRANDMA, HOME, SCHOOL, family_fixes

UTC_TZ = ZoneInfo("UTC")


def _stays(days: int = 21, only: tuple[str, ...] = ("Kai", "Mia")) -> dict[str, list[Stay]]:
    fixes = family_fixes(days)
    params = SegmentParams(dwell_min=MIN_STAY_MIN)
    return {n: segment(f, params).stays for n, f in fixes.items() if n in only}


def _near(c: dict, point, metres: float = 60.0) -> bool:
    return haversine_meters(c["lat"], c["lon"], *point) <= metres


@pytest.fixture(scope="module")
def found() -> list[dict]:
    return find_candidates(_stays(), UTC_TZ)


def test_finds_home_school_and_grandmas_and_nothing_else(found) -> None:
    assert len(found) == 3
    assert sum(_near(c, HOME) for c in found) == 1
    assert sum(_near(c, SCHOOL) for c in found) == 1
    assert sum(_near(c, GRANDMA) for c in found) == 1


def test_home_is_first_and_guessed_from_the_nights(found) -> None:
    assert found[0]["kind_guess"] == "home" and _near(found[0], HOME)
    assert found[0]["nights"] >= 18


def test_school_is_a_weekday_daytime_guess_with_its_hours(found) -> None:
    school = next(c for c in found if _near(c, SCHOOL))
    assert school["kind_guess"] == "school_or_work"
    assert school["days"] == 15 and school["nights"] == 0
    assert school["typical"]["days"] == "weekdays"
    assert 8 * 60 <= school["typical"]["start_min"] <= 8 * 60 + 40
    assert 14 * 60 + 30 <= school["typical"]["end_min"] <= 15 * 60 + 30
    assert school["trackers"] == ["Kai"]


def test_grandmas_is_only_a_regular_stop_on_weekends(found) -> None:
    gran = next(c for c in found if _near(c, GRANDMA))
    assert gran["kind_guess"] == "regular"
    assert gran["typical"]["days"] == "weekends"
    assert gran["days"] == 3 and gran["trackers"] == ["Kai", "Mia"]


def test_two_trackers_at_once_are_one_visit(found) -> None:
    gran = next(c for c in found if _near(c, GRANDMA))
    assert gran["visits"] == 3


def test_coordinates_are_the_data_not_the_input(found) -> None:
    for c in found:
        assert 100 <= c["radius_m"] <= 250
    assert set(found[0]) == {
        "lat",
        "lon",
        "radius_m",
        "visits",
        "days",
        "nights",
        "typical",
        "kind_guess",
        "trackers",
    }


def test_a_saved_place_is_not_suggested_again() -> None:
    saved = [(HOME[0], HOME[1], 100.0)]
    got = find_candidates(_stays(), UTC_TZ, saved, has_home=True)
    assert len(got) == 2
    assert not any(c["kind_guess"] == "home" for c in got)


def test_a_dismissed_spot_is_left_out() -> None:
    got = find_candidates(_stays(), UTC_TZ, dismissed=[GRANDMA])
    assert not any(_near(c, GRANDMA) for c in got)
    assert len(got) == 2


def test_too_little_history_gives_nothing() -> None:
    assert find_candidates(_stays(days=2), UTC_TZ) == []


def test_a_short_stop_is_not_a_place() -> None:
    t0 = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
    stays = [
        Stay(
            f"s{i}",
            t0 + timedelta(days=i),
            t0 + timedelta(days=i, minutes=30),
            41.0,
            -80.0,
            50,
            4,
            5.0,
        )
        for i in range(6)
    ]
    assert find_candidates({"Kai": stays}, UTC_TZ) == []


def test_no_names_are_invented(found) -> None:
    assert all("name" not in c for c in found)

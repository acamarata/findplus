"""cli/src/findplus/groups/presence.py — member_status and group_presence."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from findplus.groups.presence import Fix, MemberInput, group_presence, member_status

NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
BASE_LAT, BASE_LON = 41.0, -80.0
_DEG_M = math.radians(1) * 6_371_008.8  # metres per degree latitude, same formula as geo.py


def _north(meters: float) -> tuple[float, float]:
    """A point `meters` due north of BASE_LAT/BASE_LON (exact along one meridian)."""
    return BASE_LAT + meters / _DEG_M, BASE_LON


def _fix(offset_m: float, minutes_ago: float, accuracy: float | None = 25.0) -> Fix:
    lat, lon = _north(offset_m)
    when = NOW - timedelta(minutes=minutes_ago)
    return Fix(
        observation_id=1,
        device_id="d",
        latitude_e7=round(lat * 1e7),
        longitude_e7=round(lon * 1e7),
        accuracy_meters=accuracy,
        observed_at=when,
        fetched_at=when,
    )


def _member(
    device_id: str,
    name: str,
    *,
    offset_m: float = 0,
    minutes_ago: float = 5,
    accuracy: float | None = 25.0,
    inside_places: list[str] | None = None,
    prev_fix: Fix | None = None,
) -> MemberInput:
    return MemberInput(
        device_id=device_id,
        name=name,
        last_fix=_fix(offset_m, minutes_ago, accuracy),
        prev_fix=prev_fix,
        inside_places=inside_places or [],
    )


def test_three_together_at_school() -> None:
    members = [
        _member("d1", "Bike", offset_m=0, inside_places=["School"]),
        _member("d2", "Backpack", offset_m=20, inside_places=["School"]),
        _member("d3", "Shoes", offset_m=40, inside_places=["School"]),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "all_together"
    assert len(r.together) == 3
    assert "School" in r.note


def test_shoes_diverged() -> None:
    members = [
        _member("d1", "Bike", offset_m=0),
        _member("d2", "Backpack", offset_m=80),
        _member("d3", "Shoes", offset_m=2080),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "partial"
    assert r.diverged == ["Shoes"]


def test_stale_backpack_others_together() -> None:
    members = [
        _member("d1", "Bike", offset_m=0),
        _member("d2", "Backpack", offset_m=0, minutes_ago=240),
        _member("d3", "Shoes", offset_m=40),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "all_together"
    assert r.stale == ["Backpack"]
    assert "Backpack" in r.note


def test_all_stale_unknown() -> None:
    members = [_member(f"d{i}", n, minutes_ago=240) for i, n in enumerate(["A", "B", "C"])]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "unknown"
    assert r.note.startswith("No member of")
    assert "home" not in r.note


def test_all_stale_not_left_behind() -> None:
    members = [_member(f"d{i}", n, minutes_ago=240) for i, n in enumerate(["A", "B", "C"])]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert "left behind" not in r.note


def test_single_member_never_all_together() -> None:
    members = [_member("d1", "Solo", inside_places=["Home"])]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "partial"


def test_zero_reporting_note() -> None:
    members = [_member("d1", "A", minutes_ago=240)]
    r = group_presence(3, members, NOW, 90, 150, 25.0, 60)
    assert r.note.startswith("No member of group 3")


def test_one_reporting_with_stale_note() -> None:
    members = [
        _member("d1", "A"),
        _member("d2", "B", minutes_ago=240),
        _member("d3", "C", minutes_ago=240),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert "does not mean they were left behind" in r.note


def test_one_reporting_no_stale_note() -> None:
    members = [_member("d1", "A")]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert "left behind" not in r.note


def test_two_apart_partial() -> None:
    members = [
        _member("d1", "A", offset_m=0, accuracy=30),
        _member("d2", "B", offset_m=500, accuracy=30),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "partial"


def test_two_together_within_cluster() -> None:
    members = [
        _member("d1", "A", offset_m=0, accuracy=30),
        _member("d2", "B", offset_m=100, accuracy=30),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "all_together"


def test_accuracy_boundary_at() -> None:
    # 179.9 m, not exactly 180: e7-degree rounding of the two fixture points
    # (~1 cm grid) can otherwise push a "180.000" fixture a few mm over the
    # 150 + max(30, 30) = 180 m threshold and flip the expected verdict.
    members = [
        _member("d1", "A", offset_m=0, accuracy=30),
        _member("d2", "B", offset_m=179.9, accuracy=30),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "all_together"


def test_accuracy_boundary_over() -> None:
    members = [
        _member("d1", "A", offset_m=0, accuracy=30),
        _member("d2", "B", offset_m=181, accuracy=30),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "partial"


def test_accuracy_none_uses_100() -> None:
    members = [
        _member("d1", "A", offset_m=0, accuracy=None),
        _member("d2", "B", offset_m=245, accuracy=None),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "all_together"


def test_moving_status_threshold() -> None:
    same_point = member_status(
        MemberInput("d1", "A", _fix(0, 5), _fix(0, 30), []), NOW, 90, 25.0, 60
    )
    assert same_point.status == "unknown"

    moved = member_status(MemberInput("d1", "A", _fix(30, 5), _fix(0, 30), []), NOW, 90, 25.0, 60)
    assert moved.status == "moving"


def test_present_at_place_takes_priority() -> None:
    s = member_status(
        MemberInput("d1", "A", _fix(30, 5), _fix(0, 30), ["Mosque"]), NOW, 90, 25.0, 60
    )
    assert s.status == "present_at_place"


def test_stale_by_age() -> None:
    m = MemberInput("d1", "A", _fix(0, 91), None, [])
    s = member_status(m, NOW, 90, 25.0, 60)
    assert s.status == "stale"


def test_not_stale_at_boundary() -> None:
    m = MemberInput("d1", "A", _fix(0, 89), None, [])
    s = member_status(m, NOW, 90, 25.0, 60)
    assert s.status != "stale"


def test_naive_now_raises() -> None:
    m = MemberInput("d1", "A", _fix(0, 5), None, [])
    with pytest.raises(ValueError):
        member_status(m, datetime.now(), 90, 25.0, 60)


def test_note_uses_each_other_when_no_place() -> None:
    members = [
        _member("d1", "A", offset_m=0),
        _member("d2", "B", offset_m=20),
        _member("d3", "C", offset_m=40),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert "each other" in r.note


def test_stale_clause_omitted_when_no_stale() -> None:
    members = [_member("d1", "A", offset_m=0), _member("d2", "B", offset_m=20)]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert "have no recent fix" not in r.note


def test_considered_count_includes_stale() -> None:
    members = [_member("d1", "A"), _member("d2", "B"), _member("d3", "C", minutes_ago=240)]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.considered_count == 3


def test_stale_suffix_is_semicolon_joined_when_together() -> None:
    """engines.md: `<n> tags together near <place>; <names> have no recent fix.`

    Reusing the 0/1-reporting sentence here ran the two statements together
    ("... near Home Backpack have no recent fix ...").
    """
    members = [
        _member("d1", "Bike", offset_m=0, inside_places=["Home"]),
        _member("d2", "Shoes", offset_m=20, inside_places=["Home"]),
        _member("d3", "Backpack", minutes_ago=240),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "all_together"
    assert r.note == "2 tags together near Home; Backpack have no recent fix."


def test_stale_suffix_is_semicolon_joined_when_partial() -> None:
    members = [
        _member("d1", "Bike", offset_m=0),
        _member("d2", "Shoes", offset_m=600),
        _member("d3", "Backpack", minutes_ago=240),
    ]
    r = group_presence(1, members, NOW, 90, 150, 25.0, 60)
    assert r.verdict == "partial"
    assert "apart); Backpack have no recent fix." in r.note
    assert "left behind" not in r.note

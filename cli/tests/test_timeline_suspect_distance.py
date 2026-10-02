"""A sighting that looks wrong adds nothing to a day's distance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from findplus.timeline import build_timeline, compute_stats


def _obs(minute: int, lat: float, lon: float) -> SimpleNamespace:
    when = datetime(2026, 9, 18, 10, 0, tzinfo=UTC) + timedelta(minutes=minute)
    return SimpleNamespace(
        id=minute + 1, observed_at=when, first_fetched_at=when, latitude=lat, longitude=lon,
        accuracy_meters=20.0, altitude_meters=None, source=None, is_own_report=None,
        battery_level=None, times_returned=1,
    )  # fmt: skip


def _points(rows: list[SimpleNamespace]):
    return build_timeline(
        rows, tz=ZoneInfo("UTC"), movement_threshold_meters=20, gap_threshold_minutes=60
    )


def test_distance_skips_a_suspect_point() -> None:
    pts = _points([_obs(0, 41.10, -80.10), _obs(1, 41.13, -80.10), _obs(2, 41.1001, -80.10)])
    plain = compute_stats(pts).approximate_distance_meters
    pts[1].suspect = True
    trusted = compute_stats(pts).approximate_distance_meters
    assert plain > 6000, "the jump out and back counts when nothing is flagged"
    assert trusted < 50, "with the middle fix flagged only the real 11 m remains"


def test_distance_is_unchanged_when_nothing_is_suspect() -> None:
    pts = _points([_obs(0, 41.10, -80.10), _obs(5, 41.11, -80.10)])
    assert compute_stats(pts).approximate_distance_meters == pts[1].meters_from_previous

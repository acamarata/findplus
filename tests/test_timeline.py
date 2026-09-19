"""Day grouping, timezone/DST handling, gaps, movement flags and statistics."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from bike_tracker.db.models import LocationObservation
from bike_tracker.ingest import ingest_observations
from bike_tracker.timeline import (
    build_timeline,
    compute_stats,
    day_bounds_utc,
    day_timeline,
    days_with_data,
)
from tests.conftest import make_observation


# ----------------------------------------------------------- day boundaries
def test_day_bounds_cover_exactly_one_local_day(eastern: ZoneInfo) -> None:
    start, end = day_bounds_utc(date(2026, 9, 18), eastern)
    assert start == datetime(2026, 9, 18, 4, 0, tzinfo=UTC)  # EDT = UTC-4
    assert end == datetime(2026, 9, 19, 4, 0, tzinfo=UTC)


def test_spring_forward_day_is_23_hours(eastern: ZoneInfo) -> None:
    start, end = day_bounds_utc(date(2026, 3, 8), eastern)
    assert (end - start) == timedelta(hours=23)


def test_fall_back_day_is_25_hours(eastern: ZoneInfo) -> None:
    start, end = day_bounds_utc(date(2026, 11, 1), eastern)
    assert (end - start) == timedelta(hours=25)


def test_consecutive_days_abut_exactly_across_dst(eastern: ZoneInfo) -> None:
    """No lost or double-counted second at a DST boundary."""
    _, end_before = day_bounds_utc(date(2026, 3, 7), eastern)
    start_after, _ = day_bounds_utc(date(2026, 3, 8), eastern)
    assert end_before == start_after


def test_observation_late_at_night_lands_on_the_local_day(session, eastern: ZoneInfo) -> None:
    """23:30 local on the 18th is 03:30 UTC on the 19th — it belongs to the 18th."""
    local_late = datetime(2026, 9, 18, 23, 30, tzinfo=eastern)
    ingest_observations(session, [make_observation(observed_at=local_late.astimezone(UTC))])

    on_18th = day_timeline(
        session,
        "TAG-001",
        date(2026, 9, 18),
        tz=eastern,
        movement_threshold_meters=25,
        gap_threshold_minutes=20,
    )
    on_19th = day_timeline(
        session,
        "TAG-001",
        date(2026, 9, 19),
        tz=eastern,
        movement_threshold_meters=25,
        gap_threshold_minutes=20,
    )
    assert on_18th.stats.observation_count == 1
    assert on_19th.stats.observation_count == 0


def test_days_with_data_uses_local_dates(session, eastern: ZoneInfo) -> None:
    ingest_observations(
        session,
        [
            make_observation(
                observed_at=datetime(2026, 9, 18, 23, 30, tzinfo=eastern).astimezone(UTC)
            ),
            make_observation(
                observed_at=datetime(2026, 9, 20, 9, 0, tzinfo=eastern).astimezone(UTC), lat=41.2
            ),
        ],
    )
    assert days_with_data(session, "TAG-001", eastern) == ["2026-09-18", "2026-09-20"]


# ----------------------------------------------------------------- timeline
def _rows(session, device_id="TAG-001"):
    from sqlalchemy import select

    return list(
        session.scalars(
            select(LocationObservation)
            .where(LocationObservation.device_id == device_id)
            .order_by(LocationObservation.observed_at)
        )
    )


def test_timeline_is_sequenced_and_first_point_has_no_previous(session, eastern) -> None:
    ingest_observations(
        session, [make_observation(minutes=m, lat=41.1 + m / 500) for m in (0, 15, 34)]
    )
    points = build_timeline(
        _rows(session), tz=eastern, movement_threshold_meters=25, gap_threshold_minutes=20
    )
    assert [p.sequence for p in points] == [1, 2, 3]
    assert points[0].seconds_since_previous is None
    assert points[0].meters_from_previous is None
    assert points[0].is_movement is True  # the anchor point always counts
    assert points[1].seconds_since_previous == 15 * 60


def test_jitter_below_threshold_is_flagged_but_retained(session, eastern) -> None:
    """Raw data is never dropped; the UI just distinguishes it."""
    ingest_observations(
        session,
        [
            make_observation(minutes=0, lat=41.100000),
            make_observation(minutes=5, lat=41.1000900),  # ~10 m away
            make_observation(minutes=10, lat=41.105000),  # ~555 m away
        ],
    )
    points = build_timeline(
        _rows(session), tz=eastern, movement_threshold_meters=25, gap_threshold_minutes=20
    )
    assert len(points) == 3, "jitter observations must still be present"
    assert points[1].is_movement is False
    assert points[2].is_movement is True


def test_movement_threshold_is_configurable(session, eastern) -> None:
    ingest_observations(
        session,
        [
            make_observation(minutes=0, lat=41.100000),
            make_observation(minutes=5, lat=41.1009000),  # ~100 m
        ],
    )
    rows = _rows(session)
    strict = build_timeline(
        rows, tz=eastern, movement_threshold_meters=25, gap_threshold_minutes=20
    )
    loose = build_timeline(
        rows, tz=eastern, movement_threshold_meters=250, gap_threshold_minutes=20
    )
    assert strict[1].is_movement is True
    assert loose[1].is_movement is False


# --------------------------------------------------------------------- gaps
def test_gap_is_flagged_only_when_over_threshold(session, eastern) -> None:
    ingest_observations(
        session,
        [
            make_observation(minutes=0, lat=41.10),
            make_observation(minutes=10, lat=41.11),  # 10 min: no gap
            make_observation(minutes=57, lat=41.12),  # 47 min later: gap
        ],
    )
    points = build_timeline(
        _rows(session), tz=eastern, movement_threshold_meters=25, gap_threshold_minutes=20
    )
    assert points[0].gap_before is False
    assert points[1].gap_before is False
    assert points[2].gap_before is True
    assert points[2].seconds_since_previous == 47 * 60


def test_gap_threshold_boundary_is_strict(session, eastern) -> None:
    ingest_observations(
        session,
        [
            make_observation(minutes=0, lat=41.10),
            make_observation(minutes=20, lat=41.11),
        ],
    )
    points = build_timeline(
        _rows(session), tz=eastern, movement_threshold_meters=25, gap_threshold_minutes=20
    )
    assert points[1].gap_before is False, "exactly the threshold is not yet a gap"


def test_no_interpolation_across_a_gap(session, eastern) -> None:
    """A 47-minute gap must produce two points, never invented intermediates."""
    ingest_observations(
        session,
        [
            make_observation(minutes=0, lat=41.10),
            make_observation(minutes=47, lat=41.30),
        ],
    )
    points = build_timeline(
        _rows(session), tz=eastern, movement_threshold_meters=25, gap_threshold_minutes=20
    )
    assert len(points) == 2


# --------------------------------------------------------------- statistics
def test_stats_on_empty_day_are_zeroed() -> None:
    stats = compute_stats([])
    assert stats.observation_count == 0
    assert stats.approximate_distance_meters == 0.0
    assert stats.first_observed_at is None


def test_stats_aggregate_correctly(session, eastern) -> None:
    ingest_observations(
        session,
        [
            make_observation(minutes=0, lat=41.100),
            make_observation(minutes=20, lat=41.110),
            make_observation(minutes=75, lat=41.120),
        ],
    )
    points = build_timeline(
        _rows(session), tz=eastern, movement_threshold_meters=25, gap_threshold_minutes=20
    )
    stats = compute_stats(points)

    assert stats.observation_count == 3
    assert stats.time_span_seconds == 75 * 60
    assert stats.longest_gap_seconds == 55 * 60
    # Two ~1.11 km hops.
    assert stats.approximate_distance_meters == pytest.approx(2224, abs=30)
    assert stats.approximate_distance_miles == pytest.approx(1.382, abs=0.05)
    assert "Approximate distance between observed locations" in stats.distance_label


def test_single_observation_has_zero_span_and_distance(session, eastern) -> None:
    ingest_observations(session, [make_observation(minutes=0)])
    points = build_timeline(
        _rows(session), tz=eastern, movement_threshold_meters=25, gap_threshold_minutes=20
    )
    stats = compute_stats(points)
    assert stats.observation_count == 1
    assert stats.time_span_seconds == 0
    assert stats.approximate_distance_meters == 0.0
    assert stats.longest_gap_seconds == 0.0


def test_day_timeline_payload_carries_the_route_disclaimer(session, eastern) -> None:
    ingest_observations(session, [make_observation(minutes=0)])
    payload = day_timeline(
        session,
        "TAG-001",
        date(2026, 9, 18),
        tz=eastern,
        movement_threshold_meters=25,
        gap_threshold_minutes=20,
    ).to_dict()
    assert "actual route between detections may differ" in payload["path_disclaimer"]

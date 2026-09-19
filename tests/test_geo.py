"""Haversine distance and movement thresholding."""

from __future__ import annotations

import pytest

from findplus.geo import haversine_meters, is_meaningful_movement, meters_to_miles


def test_zero_distance_for_identical_points() -> None:
    assert haversine_meters(41.5, -80.5, 41.5, -80.5) == 0.0


def test_known_distance_new_york_to_los_angeles() -> None:
    # Published great-circle distance is ~3,936 km for these coordinates.
    meters = haversine_meters(40.7128, -74.0060, 34.0522, -118.2437)
    assert 3_930_000 < meters < 3_945_000


def test_one_degree_of_latitude_is_about_111km() -> None:
    meters = haversine_meters(0.0, 0.0, 1.0, 0.0)
    assert 111_000 < meters < 111_400


def test_symmetry() -> None:
    a = haversine_meters(41.1, -80.1, 41.2, -80.2)
    b = haversine_meters(41.2, -80.2, 41.1, -80.1)
    assert a == pytest.approx(b)


def test_antimeridian_is_short_not_long_way_round() -> None:
    meters = haversine_meters(0.0, 179.9, 0.0, -179.9)
    assert meters < 25_000  # ~22 km, not ~40,000 km


def test_small_hop_matches_expected_magnitude() -> None:
    # 0.001 degrees of latitude is ~111 m.
    assert haversine_meters(41.0, -80.0, 41.001, -80.0) == pytest.approx(111.2, abs=1.0)


def test_meters_to_miles() -> None:
    assert meters_to_miles(1609.344) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("distance", "threshold", "expected"),
    [
        (0.0, 25.0, False),
        (24.9, 25.0, False),
        (25.0, 25.0, False),
        (25.1, 25.0, True),
        (500.0, 25.0, True),
        (10.0, 0.0, True),
    ],
)
def test_movement_threshold_is_strictly_greater_than(
    distance: float, threshold: float, expected: bool
) -> None:
    assert is_meaningful_movement(distance, threshold) is expected

"""Geodesic helpers.

Purpose : Distance maths and movement classification over observed locations.
Inputs  : Latitude/longitude pairs in decimal degrees.
Outputs : Distances in metres; movement flags.
Constraints:
    - Haversine on a spherical earth. Accurate to ~0.5% — far below the accuracy
      floor of crowdsourced Bluetooth observations, so the approximation is not
      the limiting factor here.
    - Distances between observations are NOT travelled distance. See ARCHITECTURE.md.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_METERS = 6_371_008.8
METERS_PER_MILE = 1609.344


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in metres."""
    p1, p2 = radians(lat1), radians(lat2)
    dphi = p2 - p1
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * asin(sqrt(min(1.0, a)))


def meters_to_miles(meters: float) -> float:
    return meters / METERS_PER_MILE


def is_meaningful_movement(distance_meters: float, threshold_meters: float) -> bool:
    """True when a hop exceeds the jitter threshold.

    Bluetooth/crowdsourced fixes wander by tens of metres while stationary; the
    threshold suppresses that without discarding the underlying observation.
    """
    return distance_meters > threshold_meters

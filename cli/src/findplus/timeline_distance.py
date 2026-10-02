"""A day's distance, leaving out sightings that look wrong.

Purpose : A tag that jumps 2 km away and back would add 4 km to the day's distance. The
          quality check marks such a sighting `suspect`; this sums only the rest.
Inputs  : The day's TimelinePoints, already annotated (`suspect`).
Outputs : Metres between consecutive trusted sightings.
Constraints: With no suspect point the answer is exactly the sum of each point's own
          `meters_from_previous`, so a normal day does not change.
"""

from __future__ import annotations

from itertools import pairwise

from findplus.geo import haversine_meters
from findplus.timeline_models import TimelinePoint


def trusted_distance(points: list[TimelinePoint]) -> float:
    """Distance between consecutive sightings, leaving out any that look wrong."""
    if not any(p.suspect for p in points):
        return sum(p.meters_from_previous or 0.0 for p in points)
    good = [p for p in points if not p.suspect]
    return sum(
        haversine_meters(a.latitude, a.longitude, b.latitude, b.longitude)
        for a, b in pairwise(good)
    )

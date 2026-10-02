"""Group consecutive fixes into dwell clusters around a running centroid.

Purpose    : Find the places a tag stayed, ignoring jitter inside the accuracy
             circle. This is the heart of "ignore noise when someone is home".
Inputs     : Fixes (outliers already removed), sorted by time.
Outputs    : Clusters (lists of fixes). A cluster is a STAY when it spans at
             least `dwell_min` minutes; shorter ones are movement.
Constraints: A fix joins the open cluster when it lies within
             max(min_radius_m, accuracy_factor x its own accuracy) of the
             cluster's running centroid. Pure; no clock, DB or network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from findplus.geo import haversine_meters
from findplus.trips.models import Fix


@dataclass
class Cluster:
    """An open or closed run of fixes with a running mean position."""

    fixes: list[Fix] = field(default_factory=list)
    lat: float = 0.0
    lon: float = 0.0

    def add(self, fix: Fix) -> None:
        n = len(self.fixes)
        self.lat = (self.lat * n + fix.lat) / (n + 1)
        self.lon = (self.lon * n + fix.lon) / (n + 1)
        self.fixes.append(fix)

    def reach(self, fix: Fix) -> float:
        return haversine_meters(self.lat, self.lon, fix.lat, fix.lon)

    @property
    def span_min(self) -> float:
        return (self.fixes[-1].t - self.fixes[0].t).total_seconds() / 60.0

    @property
    def radius_m(self) -> float:
        return max((self.reach(f) for f in self.fixes), default=0.0)


def join_radius(fix: Fix, min_radius_m: float, accuracy_factor: float) -> float:
    """How far from the centroid this fix may be and still count as 'same place'."""
    return max(min_radius_m, accuracy_factor * fix.acc)


def build_clusters(
    fixes: list[Fix], min_radius_m: float = 75.0, accuracy_factor: float = 1.5
) -> list[Cluster]:
    """Sweep the fixes once, closing a cluster when a fix lands outside its circle."""
    clusters: list[Cluster] = []
    current = Cluster()
    for fix in fixes:
        if current.fixes and current.reach(fix) > join_radius(fix, min_radius_m, accuracy_factor):
            clusters.append(current)
            current = Cluster()
        current.add(fix)
    if current.fixes:
        clusters.append(current)
    return clusters

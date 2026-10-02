"""Segment one device's fixes into stays, trips, gaps and dropped outliers.

Purpose    : The single entry point the API, CLI and MCP tool share.
Inputs     : Fixes (any order), SegmentParams, an optional place lookup.
Outputs    : `Segmentation` with stays, trips, gaps, the kept/dropped fix counts.
Constraints: Pure. Distance on a trip is the sum of straight lines between the
             sightings on it, so it is APPROXIMATE and never road distance.
             Raw fixes are never altered or deleted; outliers are only left out
             of stays and trips and returned in `dropped`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

from findplus.geo import haversine_meters
from findplus.trips.clusters import build_clusters
from findplus.trips.models import Fix, Gap, Stay, TripLeg
from findplus.trips.outliers import MAX_SPEED_MPS, Verdicts, classify_outliers
from findplus.trips.stays import (
    Block,
    PlaceLookup,
    attach_places,
    merge_blocks,
    split_blocks,
)


@dataclass(frozen=True, slots=True)
class SegmentParams:
    """Thresholds. Defaults are recorded in .claude/memory/decisions.md."""

    dwell_min: float = 10.0
    min_radius_m: float = 75.0
    accuracy_factor: float = 1.5
    gap_min: float = 60.0
    max_speed_mps: float = MAX_SPEED_MPS


@dataclass
class Segmentation:
    stays: list[Stay] = field(default_factory=list)
    trips: list[TripLeg] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    dropped: list[Fix] = field(default_factory=list)
    #: Reason codes (quality.rules) for each dropped fix id.
    reasons: dict[int, tuple[str, ...]] = field(default_factory=dict)
    fix_count: int = 0


def _longest_gap_min(fixes: list[Fix] | tuple[Fix, ...]) -> float:
    pairs = pairwise(fixes)
    return max(((b.t - a.t).total_seconds() / 60.0 for a, b in pairs), default=0.0)


def _path_m(points: list[Fix]) -> float:
    return sum(haversine_meters(a.lat, a.lon, b.lat, b.lon) for a, b in pairwise(points))


def _stay_from(block: Block, index: int) -> Stay:
    c = block.cluster
    place = block.place
    return Stay(
        id=f"s{index}",
        start=c.fixes[0].t,
        end=c.fixes[-1].t,
        lat=c.lat,
        lon=c.lon,
        radius_m=round(c.radius_m),
        fix_count=len(c.fixes),
        longest_gap_min=_longest_gap_min(c.fixes),
        place_id=place[0] if place else None,
        place_name=place[1] if place else None,
    )


def _leg(moving: list[Fix], before: Block | None, after: Block | None, ids) -> TripLeg | None:
    """One trip from the moving fixes between two stays (either end may be open)."""
    points = [*([before.cluster.fixes[-1]] if before else []), *moving]
    points += [after.cluster.fixes[0]] if after else []
    if len(points) < 2:
        return None
    if not before and not after and _path_m(points) < 2 * 75.0:
        return None
    return TripLeg(
        id=f"t{int(points[0].t.timestamp())}",
        start=points[0].t,
        end=points[-1].t,
        from_stay=ids.get(id(before)),
        to_stay=ids.get(id(after)),
        points=tuple(points),
        distance_m=_path_m(points),
        fix_count=len(moving),
        longest_gap_min=_longest_gap_min(points),
    )


def _build_trips(leading: list[Fix], blocks: list[Block], ids: dict[int, str]) -> list[TripLeg]:
    legs: list[TripLeg | None] = []
    if not blocks:
        legs.append(_leg(leading, None, None, ids))
    else:
        legs.append(_leg(leading, None, blocks[0], ids) if leading else None)
        for a, b in pairwise(blocks):
            legs.append(_leg(a.after, a, b, ids))
        if blocks[-1].after:
            legs.append(_leg(blocks[-1].after, blocks[-1], None, ids))
    return [leg for leg in legs if leg is not None]


def _find_gaps(fixes: list[Fix], stays: list[Stay], trips: list[TripLeg], gap_min: float):
    gaps: list[Gap] = []
    for a, b in pairwise(fixes):
        if (b.t - a.t).total_seconds() / 60.0 <= gap_min:
            continue
        inside = next((s.id for s in stays if s.start <= a.t and b.t <= s.end), None)
        inside = inside or next((t.id for t in trips if t.start <= a.t and b.t <= t.end), None)
        gaps.append(Gap(a.t, b.t, inside))
    return gaps


def segment(
    fixes: list[Fix],
    params: SegmentParams | None = None,
    lookup: PlaceLookup | None = None,
    verdicts: Verdicts | None = None,
) -> Segmentation:
    """Stays, trips and gaps for one device's fixes. Empty input gives an empty result.

    `verdicts` are the stored quality verdicts; without them the pure rules decide.
    """
    p = params or SegmentParams()
    ordered = sorted(fixes, key=lambda f: (f.t, f.id))
    result = Segmentation(fix_count=len(ordered))
    if not ordered:
        return result
    kept, result.dropped, result.reasons = classify_outliers(ordered, p.max_speed_mps, verdicts)
    clusters = build_clusters(kept, p.min_radius_m, p.accuracy_factor)
    leading, blocks = split_blocks(clusters, p.dwell_min)
    attach_places(blocks, lookup)
    blocks = merge_blocks(blocks, 2 * p.min_radius_m, 3 * p.min_radius_m + 25)
    result.stays = [_stay_from(b, i) for i, b in enumerate(blocks)]
    ids = {id(b): s.id for b, s in zip(blocks, result.stays, strict=True)}
    result.trips = _build_trips(leading, blocks, ids)
    result.gaps = _find_gaps(ordered, result.stays, result.trips, p.gap_min)
    return result

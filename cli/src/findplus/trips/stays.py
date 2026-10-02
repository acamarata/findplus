"""Turn clusters into stays, absorbing brief wobble between near-identical stays.

Purpose    : Decide which clusters are real stays, merge the ones that are the
             same place seen twice with only jitter between them, and attach a
             saved-place label. Jitter must never create a trip.
Inputs     : Clusters from `build_clusters`, a place lookup, SegmentParams.
Outputs    : Ordered `Block`s: a stay block (cluster + moving fixes after it).
Constraints: Two stays merge when the fixes between them stay within
             `excursion_m` of the earlier stay AND (their centres are within
             `merge_m` OR both sit in the same saved place). A long gap does
             not stop a merge; the gap is reported separately.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from findplus.geo import haversine_meters
from findplus.trips.clusters import Cluster
from findplus.trips.models import Fix

#: (lat, lon, accuracy_m) -> (place_id, place_name) or None.
PlaceLookup = Callable[[float, float, float], "tuple[int, str] | None"]


@dataclass
class Block:
    """One stay cluster plus the moving fixes that follow it before the next stay."""

    cluster: Cluster
    place: tuple[int, str] | None = None
    after: list[Fix] = field(default_factory=list)


def _median_acc(cluster: Cluster) -> float:
    accs = sorted(f.acc for f in cluster.fixes)
    return accs[len(accs) // 2]


def _place_of(cluster: Cluster, lookup: PlaceLookup | None):
    return lookup(cluster.lat, cluster.lon, _median_acc(cluster)) if lookup else None


def _can_merge(a: Block, b: Block, merge_m: float, excursion_m: float) -> bool:
    """True when `b` is `a` again, with only small wobble in between."""
    if any(a.cluster.reach(f) > excursion_m for f in a.after):
        return False
    close = haversine_meters(a.cluster.lat, a.cluster.lon, b.cluster.lat, b.cluster.lon) <= merge_m
    same_place = a.place is not None and b.place is not None and a.place[0] == b.place[0]
    return close or same_place


def _absorb(a: Block, b: Block) -> Block:
    merged = Cluster()
    for fix in (*a.cluster.fixes, *a.after, *b.cluster.fixes):
        merged.add(fix)
    return Block(merged, a.place or b.place, b.after)


def merge_blocks(
    blocks: list[Block], merge_m: float = 150.0, excursion_m: float = 250.0
) -> list[Block]:
    """Fold neighbouring blocks that are the same stay split by jitter."""
    out: list[Block] = []
    for block in blocks:
        if out and _can_merge(out[-1], block, merge_m, excursion_m):
            out[-1] = _absorb(out[-1], block)
        else:
            out.append(block)
    return out


def attach_places(blocks: list[Block], lookup: PlaceLookup | None) -> None:
    """Label each block with the saved place its centre falls inside, if any."""
    for block in blocks:
        block.place = _place_of(block.cluster, lookup)


def split_blocks(clusters: list[Cluster], dwell_min: float) -> tuple[list[Fix], list[Block]]:
    """(leading moving fixes, stay blocks). Short clusters are movement.

    When nothing qualifies but the data is one tight cluster (a device that
    simply sat still for a few minutes), that cluster is returned as a stay so
    the answer is "it was here" rather than nothing.
    """
    leading: list[Fix] = []
    blocks: list[Block] = []
    for cluster in clusters:
        if cluster.span_min >= dwell_min:
            blocks.append(Block(cluster))
        elif blocks:
            blocks[-1].after.extend(cluster.fixes)
        else:
            leading.extend(cluster.fixes)
    if not blocks and len(clusters) == 1:
        return [], [Block(clusters[0])]
    return leading, blocks

"""Leave suspect fixes out of stays and trips (a wrapper over `findplus.quality`).

Purpose    : A crowd-sourced fix is sometimes far from where the tag really
             was. One such fix must not become a trip out and back.
Inputs     : Fixes sorted by time; the speed ceiling in metres per second; and,
             optionally, the stored quality verdicts (`observation_quality`).
Outputs    : (kept, dropped[, reasons]). Dropped fixes stay in the raw data; they
             are only left out of stays and trips, and the API lists them with
             the reason codes from `quality.rules`.
Constraints: The rules live in `quality.rules` / `quality.score`; nothing is
             decided here. A stored verdict for a fix wins over the pure rules
             (it saw sibling trackers and rescues); a fix with no stored row falls
             back to aba_teleport, impossible_speed and edge_stray over the list.
             Two consecutive bad fixes are kept (honest over clever).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from findplus.quality.rules import MAX_SPEED_MPS
from findplus.quality.score import hard_reasons
from findplus.trips.models import Fix

__all__ = ["MAX_SPEED_MPS", "Verdicts", "classify_outliers", "drop_outliers"]

#: observation id -> (suspect, reason codes), as stored by `quality.store`.
Verdicts = Mapping[int, tuple[bool, Sequence[str]]]


def classify_outliers(
    fixes: list[Fix],
    max_speed: float = MAX_SPEED_MPS,
    verdicts: Verdicts | None = None,
) -> tuple[list[Fix], list[Fix], dict[int, tuple[str, ...]]]:
    """Split `fixes` (time-ordered) into (kept, dropped, reasons by fix id)."""
    pure = hard_reasons(fixes, max_speed) if len(fixes) >= 3 else {}
    kept: list[Fix] = []
    dropped: list[Fix] = []
    reasons: dict[int, tuple[str, ...]] = {}
    for i, fix in enumerate(fixes):
        stored = (verdicts or {}).get(fix.id)
        if stored is not None:
            bad, why = stored
        else:
            why = tuple(pure.get(i, ()))
            bad = bool(why)
        if bad:
            dropped.append(fix)
            reasons[fix.id] = tuple(why)
        else:
            kept.append(fix)
    return kept, dropped, reasons


def drop_outliers(
    fixes: list[Fix], max_speed: float = MAX_SPEED_MPS
) -> tuple[list[Fix], list[Fix]]:
    """Split `fixes` into (kept, dropped); order is preserved in both lists."""
    kept, dropped, _ = classify_outliers(fixes, max_speed)
    return kept, dropped

"""Combine the pure rules into a score, reasons and rescue for one tracker.

Purpose    : `score_series` is the single scoring entry point for ingest,
             recompute and the trips wrapper.
Inputs     : One tracker's fixes (any order), optional sibling trackers' fixes
             keyed by id, and an optional clock (`now`) for the unconfirmed rule.
Outputs    : `{observation_id: Scored}`. Pure; order independent (it sorts by
             time then id first) and idempotent.
Constraints: A score is the product of the reason factors (own reports x 1.1,
             capped at 1). `suspect` is score < 0.5. A suspect fix that another
             fix vouches for is rescued: not suspect, score at least 0.6, and
             `corroborated_by` names the voucher.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from findplus.quality import rules as r
from findplus.quality.fix import Fix

_HARD = (r.ABA_TELEPORT, r.IMPOSSIBLE_SPEED, r.EDGE_STRAY)


@dataclass(frozen=True, slots=True)
class Scored:
    """The verdict on one observation."""

    observation_id: int
    score: float
    reasons: tuple[str, ...] = ()
    corroborated_by: int | None = None

    @property
    def suspect(self) -> bool:
        return self.score < r.SUSPECT_BELOW


def _score_of(reasons: Sequence[str], own_report: bool) -> float:
    value = 1.0
    for reason in reasons:
        value *= r.FACTORS[reason]
    if own_report:
        value = min(1.0, value * r.OWN_REPORT_BONUS)
    return round(value, 4)


def hard_reasons(
    ordered: Sequence[Fix], max_speed: float = r.MAX_SPEED_MPS
) -> dict[int, list[str]]:
    """aba_teleport, impossible_speed and edge_stray over a time-ordered list.

    Judged against the last fix not already flagged, so a stray never makes its
    healthy neighbour look like the outlier.
    """
    n = len(ordered)
    out: dict[int, list[str]] = {}
    if n < 3:
        return out
    if r.edge_stray(ordered[0], ordered[1], ordered[2], max_speed):
        out.setdefault(0, []).append(r.EDGE_STRAY)
    if r.edge_stray(ordered[-1], ordered[-2], ordered[-3], max_speed):
        out.setdefault(n - 1, []).append(r.EDGE_STRAY)
    for i in range(1, n - 1):
        prev = ordered[i - 1]
        if (i - 1) in out and i >= 2:
            prev = ordered[i - 2]
        found = out.setdefault(i, [])
        if r.impossible_speed(prev, ordered[i], ordered[i + 1], max_speed):
            found.append(r.IMPOSSIBLE_SPEED)
        if r.aba_teleport(prev, ordered[i], ordered[i + 1]):
            found.append(r.ABA_TELEPORT)
        if not found:
            del out[i]
    return out


def _unconfirmed_jump(prev: Fix | None, fix: Fix, nxt: Fix | None, now: datetime | None) -> bool:
    """A fast long hop that nothing has confirmed or contradicted yet."""
    if not r.is_jump(prev, fix):
        return False
    if nxt is None:
        # Too old to ever be confirmed: give it the benefit of the doubt.
        return now is None or (now - fix.t).total_seconds() <= r.JUMP_WINDOW_S
    return r.is_corroborating(fix, nxt)


def _soft_and_context(
    ordered: Sequence[Fix],
    sib_index: Sequence[tuple[list[float], list[Fix]]],
    now: datetime | None,
    hard: Mapping[int, list[str]],
) -> list[list[str]]:
    """Per-fix reasons: the hard ones plus jump, sibling, accuracy and clock rules."""
    out: list[list[str]] = []
    prev: Fix | None = None  # the last fix no hard rule flagged: jumps are measured from it
    for i, fix in enumerate(ordered):
        found = list(hard.get(i, []))
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        if not found and _unconfirmed_jump(prev, fix, nxt, now):
            found.append(r.JUMP_UNCONFIRMED)
        near = [c for t, f in sib_index if (c := r.nearest_in_time(t, f, fix))]
        if sib_index and r.sibling_disagree(fix, ordered[:i], near):
            found.append(r.SIBLING_DISAGREE)
        if r.low_accuracy(fix):
            found.append(r.LOW_ACCURACY)
        if r.clock_skew(fix):
            found.append(r.CLOCK_SKEW)
        out.append(found)
        if i not in hard:
            prev = fix
    return out


def _voucher(
    fix: Fix,
    i: int,
    ordered: Sequence[Fix],
    trusted: Sequence[bool],
    sib_index: Sequence[tuple[list[float], list[Fix]]],
) -> tuple[Fix | None, bool]:
    """(voucher, is_own_tracker) for a suspect fix, or (None, False)."""
    for j, other in enumerate(ordered):
        near_in_time = r.seconds(fix, other) <= r.RESCUE_OWN_WINDOW_S
        if j != i and trusted[j] and near_in_time and r.is_corroborating(fix, other):
            return other, True
    for times, fixes in sib_index:
        other = r.nearest_in_time(times, fixes, fix)
        near_in_time = other and r.seconds(fix, other) <= r.RESCUE_SIBLING_WINDOW_S
        if near_in_time and r.is_corroborating(fix, other):
            return other, False
    return None, False


def score_series(
    fixes: Sequence[Fix],
    *,
    siblings: Mapping[str, Sequence[Fix]] | None = None,
    now: datetime | None = None,
    max_speed: float = r.MAX_SPEED_MPS,
) -> dict[int, Scored]:
    """Score every fix of one tracker. `siblings` are other trackers of the same person."""
    ordered = sorted(fixes, key=lambda f: (f.t, f.id))
    sib_index = []
    for sib in (siblings or {}).values():
        s = sorted(sib, key=lambda f: (f.t, f.id))
        if s:
            sib_index.append(([f.t.timestamp() for f in s], s))
    reasons = _soft_and_context(ordered, sib_index, now, hard_reasons(ordered, max_speed))
    scores = [_score_of(rs, f.own_report) for rs, f in zip(reasons, ordered, strict=True)]
    trusted = [s >= r.SUSPECT_BELOW for s in scores]
    result = {f.id: Scored(f.id, scores[i], tuple(reasons[i])) for i, f in enumerate(ordered)}
    _rescue(ordered, reasons, trusted, sib_index, result)
    return result


def _rescue(ordered, reasons, trusted, sib_index, result: dict[int, Scored]) -> None:
    """Rescue suspect fixes a trusted neighbour vouches for (mutates `result`)."""
    index = {f.id: i for i, f in enumerate(ordered)}
    for i, fix in enumerate(ordered):
        if trusted[i]:
            continue
        voucher, own = _voucher(fix, i, ordered, trusted, sib_index)
        if voucher is None:
            continue
        old = result[fix.id]
        result[fix.id] = Scored(fix.id, max(old.score, r.RESCUED_SCORE), old.reasons, voucher.id)
        if own and r.JUMP_UNCONFIRMED in old.reasons and voucher.id in index:
            _mark_partner(result, voucher.id, fix.id)


def _mark_partner(result: dict[int, Scored], partner_id: int, jumper_id: int) -> None:
    """The fix that confirmed a jump shares the jump's 0.6: both are kept, neither is full trust."""
    p = result[partner_id]
    if r.JUMP_UNCONFIRMED in p.reasons:
        return
    result[partner_id] = Scored(
        partner_id, min(p.score, r.RESCUED_SCORE), (*p.reasons, r.JUMP_UNCONFIRMED), jumper_id
    )

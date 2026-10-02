"""Statistical check: 2,000 spikes in 200,000 synthetic rows at a 3 minute cadence.

Pass bar (review 2026-10-02): more than 90% of spikes caught, fewer than 0.5%
of real sightings flagged. The control set is the same life with no spikes.
"""

from __future__ import annotations

from datetime import timedelta

from findplus.quality.score import score_series
from tests.quality._stream import stream

ROWS = 200_000
SPIKES = 2_000
SEED = 20261002


def _suspects(fixes) -> set[int]:
    later = fixes[-1].t + timedelta(days=1)
    return {i for i, s in score_series(fixes, now=later).items() if s.suspect}


def test_spikes_are_caught_and_real_sightings_are_not() -> None:
    fixes, spikes = stream(SEED, ROWS, SPIKES)
    flagged = _suspects(fixes)
    caught = len(flagged & spikes) / len(spikes)
    false_in_spiked = len(flagged - spikes) / (ROWS - SPIKES)
    assert caught > 0.90, f"caught {caught:.3%}"
    assert false_in_spiked < 0.005, f"false flags {false_in_spiked:.3%}"


def test_the_control_life_is_almost_never_flagged() -> None:
    fixes, _ = stream(SEED, ROWS)
    flagged = _suspects(fixes)
    assert len(flagged) / ROWS < 0.005, f"false flags {len(flagged) / ROWS:.3%}"


def _scan_voucher(fix, i, ordered, times, trusted, sib_index):
    """The first rescue's linear scan, kept as the reference for the bisect one."""
    from findplus.quality import rules as r

    for j, other in enumerate(ordered):
        near = r.seconds(fix, other) <= r.RESCUE_OWN_WINDOW_S
        if j != i and trusted[j] and near and r.is_corroborating(fix, other):
            return other, True
    return None, False


def test_rescue_by_bisect_matches_a_full_scan(monkeypatch) -> None:
    """Review #7: the voucher bisects instead of scanning; the verdicts are identical."""
    from findplus.quality import score

    fixes, _ = stream(7, 4_000, 400)
    later = fixes[-1].t + timedelta(days=1)
    fast = score_series(fixes, now=later)
    monkeypatch.setattr(score, "_voucher", _scan_voucher)
    assert score_series(fixes, now=later) == fast
    assert any(s.corroborated_by for s in fast.values())

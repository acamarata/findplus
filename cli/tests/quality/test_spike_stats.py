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

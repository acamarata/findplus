"""One-fix spikes at real Find Hub cadence (1 to 10 minutes between sightings).

The owner's complaint: "at one place at 4:17, far away at 4:18, back near the
first at 4:19". The first rule only caught that at about one minute spacing;
these vectors pin it at the spacings Find Hub really uses.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from findplus.quality import rules as r
from findplus.quality.score import score_series
from tests.quality._vectors import T0, fix

LATER = T0 + timedelta(days=1)


def _spike(far_m: float, gap_min: float, back_m: float = 60.0) -> dict:
    """A at 0, B `far_m` away after `gap_min`, C `back_m` from A after another `gap_min`."""
    fixes = [fix(1, 0), fix(2, gap_min, far_m, acc=40), fix(3, 2 * gap_min, back_m)]
    return score_series(fixes, now=LATER)


@pytest.mark.parametrize("far_m", [2500, 1000, 600, 400])
def test_a_spike_one_minute_out_and_back_is_caught(far_m: float) -> None:
    out = _spike(far_m, 1)
    assert out[2].suspect and r.ABA_TELEPORT in out[2].reasons
    assert not out[1].suspect and not out[3].suspect


@pytest.mark.parametrize("gap_min", [2, 3, 5, 10])
@pytest.mark.parametrize("far_m", [1000, 2500, 6000])
def test_a_spike_at_find_hub_cadence_is_caught(far_m: float, gap_min: float) -> None:
    out = _spike(far_m, gap_min)
    assert out[2].suspect and r.ABA_TELEPORT in out[2].reasons


def test_the_return_can_come_later_than_one_minute() -> None:
    # A 4:17, B 4:18 at 2.5 km, C 4:25 (not 4:19) back near A.
    fixes = [fix(1, 0), fix(2, 1, 2500, acc=40), fix(3, 8, 60)]
    out = score_series(fixes, now=LATER)
    assert out[2].suspect and r.ABA_TELEPORT in out[2].reasons


def test_a_long_stay_somewhere_and_back_is_not_a_spike() -> None:
    # V3 again at a wider spread: 30 minutes each way is a real trip.
    out = _spike(3000, 30)
    assert not any(s.suspect for s in out.values())


def test_a_small_wobble_is_never_a_spike() -> None:
    out = _spike(250, 1)
    assert not any(s.reasons for s in out.values())


def test_a_real_quick_out_and_back_is_rescued_by_a_second_sighting() -> None:
    # A U-turn after a missed exit: two sightings at the far end vouch for each other.
    fixes = [fix(1, 0), fix(2, 3, 2000), fix(3, 4, 2050), fix(4, 7, 40)]
    out = score_series(fixes, now=LATER)
    assert not out[2].suspect and not out[3].suspect


def test_a_real_quick_out_and_back_is_rescued_by_a_sibling() -> None:
    # Only one own sighting at the far end, but the person's watch was there too.
    fixes = [fix(1, 0), fix(2, 3, 2000), fix(3, 6, 40)]
    watch = {"watch": [fix(50, 4, 2030, acc=20)]}
    out = score_series(fixes, siblings=watch, now=LATER)
    assert r.ABA_TELEPORT in out[2].reasons
    assert not out[2].suspect and out[2].corroborated_by == 50


def test_a_lone_far_fix_with_no_next_fix_is_held_regardless_of_speed() -> None:
    # 1.5 km in three minutes is only 8 m/s: still held until the next fix decides.
    held = score_series([fix(1, 0), fix(2, 3, 1500)], now=T0 + timedelta(minutes=3))
    assert held[2].suspect and held[2].reasons == (r.JUMP_UNCONFIRMED,)


def test_a_walk_is_never_held() -> None:
    held = score_series([fix(1, 0), fix(2, 3, 250)], now=T0 + timedelta(minutes=3))
    assert held[2].reasons == ()

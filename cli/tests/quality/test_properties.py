"""Property-style tests: seeded random inputs, no extra dependencies."""

from __future__ import annotations

import random
from datetime import timedelta

import pytest

from findplus.quality.score import score_series
from tests.quality._vectors import T0, fix

SEEDS = range(40)
LATER = T0 + timedelta(days=1)  # "now" long after the data: nothing is waiting on a next fix


def _drive(rng: random.Random, start_id: int = 1) -> list:
    """A drive along a straight road at 3 to 30 m/s with 1 to 10 minute gaps."""
    speed = rng.uniform(3, 30)
    minute, metres, out = 0.0, 0.0, []
    for i in range(rng.randint(4, 12)):
        out.append(fix(start_id + i, minute, metres, acc=rng.uniform(10, 80)))
        step = rng.uniform(1, 10)
        minute += step
        metres += speed * step * 60
    return out


@pytest.mark.parametrize("seed", SEEDS)
def test_a_real_drive_is_never_flagged(seed: int) -> None:
    out = score_series(_drive(random.Random(seed)), now=LATER)
    assert [s for s in out.values() if s.suspect or s.reasons] == []


@pytest.mark.parametrize("seed", SEEDS)
def test_a_school_run_with_jitter_is_never_flagged(seed: int) -> None:
    rng = random.Random(seed)
    school_m = rng.uniform(1500, 6000)
    plan = [(0, 0)] * 5 + [(25, school_m)] * 6 + [(60, 0)] * 5
    fixes = [
        fix(i + 1, m * 1.0 + 5 * i, north + rng.uniform(-40, 40), rng.uniform(-40, 40))
        for i, (m, north) in enumerate(plan)
    ]
    # Spread the minutes so every leg is at least a few minutes long.
    out = score_series(fixes, now=LATER)
    assert [s for s in out.values() if s.suspect] == []


@pytest.mark.parametrize("seed", SEEDS)
def test_scoring_does_not_depend_on_input_order(seed: int) -> None:
    rng = random.Random(seed)
    fixes = _drive(rng)
    fixes.insert(rng.randint(1, len(fixes) - 1), fix(99, rng.uniform(1, 20), 4000, acc=40))
    shuffled = fixes[:]
    rng.shuffle(shuffled)
    assert score_series(fixes, now=LATER) == score_series(shuffled, now=LATER)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_teleport_inside_a_stay_is_always_found(seed: int) -> None:
    rng = random.Random(seed)
    away = rng.uniform(1500, 30_000)
    fixes = [fix(i + 1, i * 1.0, rng.uniform(-30, 30), rng.uniform(-30, 30)) for i in range(7)]
    fixes[3] = fix(4, 3.0, away, 0, acc=40)
    out = score_series(fixes, now=LATER)
    assert out[4].suspect
    assert [i for i, s in out.items() if s.suspect] == [4]


@pytest.mark.parametrize("seed", SEEDS)
def test_scoring_twice_gives_the_same_answer(seed: int) -> None:
    fixes = _drive(random.Random(seed))
    assert score_series(fixes, now=LATER) == score_series(fixes, now=LATER)

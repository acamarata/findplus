"""A long synthetic life of one tracker at Find Hub cadence, with optional spikes.

Purpose    : The statistical bad-coordinate test: stays (with GPS jitter) and
             drives (turns, speed changes, the odd quick U-turn) sampled about
             every 3 minutes, plus a seeded set of one-fix spikes 1 to 6 km out.
Inputs     : A seed, a row count and a spike count.
Outputs    : (fixes, spike ids). Ids are unique and increase with time.
Constraints: test-only; deterministic for a seed; no DB, no network.
"""

from __future__ import annotations

import math
import random
from datetime import timedelta

from findplus.quality.fix import Fix
from tests.quality._vectors import ORIGIN, T0
from tests.trips._synth import offset

CADENCE_S = 180


def _stay(rng: random.Random, here: tuple[float, float], n: int):
    """`n` sightings around `here`, each off by noise inside its reported accuracy."""
    for _ in range(n):
        acc = rng.choice((rng.uniform(10, 60), rng.uniform(60, 150)))
        r, a = abs(rng.gauss(0, acc / 2)), rng.uniform(0, 2 * math.pi)
        yield here[0] + r * math.cos(a), here[1] + r * math.sin(a), acc


def _drive(rng: random.Random, here: tuple[float, float], n: int):
    """`n` sightings along a winding road at 5 to 30 m/s; returns via `here` updates."""
    heading = rng.uniform(0, 2 * math.pi)
    for _ in range(n):
        heading += rng.gauss(0, 0.5)
        step = rng.uniform(5, 30) * CADENCE_S * rng.uniform(0.3, 1.0)
        here[0] += step * math.cos(heading)
        here[1] += step * math.sin(heading)
        yield here[0], here[1], rng.uniform(10, 60)


def _segments(rng: random.Random):
    """Endless (north_m, east_m, acc) sightings: mostly stays, some drives."""
    here = [0.0, 0.0]
    while True:
        if rng.random() < 0.75:
            yield from _stay(rng, tuple(here), rng.randint(10, 100))
        else:
            yield from _drive(rng, here, rng.randint(2, 15))


def stream(seed: int, rows: int, spikes: int = 0) -> tuple[list[Fix], set[int]]:
    """`rows` fixes about 3 minutes apart (with the odd gap) and `spikes` one-fix spikes."""
    rng = random.Random(seed)
    spike_at = set(rng.sample(range(5, rows - 5, 3), spikes)) if spikes else set()
    out: list[Fix] = []
    t = T0
    for i, (north, east, acc) in zip(range(rows), _segments(rng), strict=False):
        t += timedelta(seconds=CADENCE_S + rng.uniform(-40, 40))
        if rng.random() < 0.01:
            t += timedelta(minutes=rng.uniform(10, 90))  # no report for a while
        if i in spike_at:
            far, a = rng.uniform(1000, 6000), rng.uniform(0, 2 * math.pi)
            north, east = north + far * math.cos(a), east + far * math.sin(a)
            acc = rng.uniform(20, 80)
        lat, lon = offset(ORIGIN, north, east)
        out.append(Fix(i + 1, t, lat, lon, acc))
    return out, {i + 1 for i in spike_at}

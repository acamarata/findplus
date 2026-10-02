"""Incremental scoring at ingest equals a full recompute, whatever the arrival order.

Review 2026-10-02 #4: a tracker's ingest did not rescore its siblings, so the
verdicts depended on which tracker's poll landed first. Here three trackers of
one person (plus an unrelated one) share a day with spikes, a solo trip and
fetch lags from seconds to 90 minutes; every poll goes through the real
ingest, with the poller's release tick in between.
"""

from __future__ import annotations

import random
from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from findplus.db.models_people import ObservationQuality
from findplus.groups.repo import create_group
from findplus.ingest import ingest_observations, release_held_fixes
from findplus.quality import store
from tests.conftest import make_observation
from tests.quality._ingest import add_tracker
from tests.quality._stream import stream

KID = ("BAG", "SHOES", "WATCH")
OTHER = "CAR"
LAGS_MIN = (0.3, 0.3, 1, 1, 3, 5, 30, 90, 180)


def _sightings(seed: int) -> list[tuple]:
    """(fetched_at, device, RawObservation) for every tracker, unsorted."""
    rng = random.Random(seed)
    path, _ = stream(seed, 160)
    # A quick real out-and-back every trackers sees: only a sibling can vouch for it.
    shared = {k: rng.uniform(0.015, 0.04) for k in range(160) if rng.random() < 0.06}
    out = []
    for n, device in enumerate((*KID, OTHER)):
        own, _ = stream(seed + 100 + n, 160, 12) if device == OTHER else (path, None)
        quiet_from = rng.randint(100, 160)  # each tracker goes quiet at its own time
        for k, f in enumerate(own[:quiet_from]):
            if device != OTHER and rng.random() < 0.35:
                continue  # each tracker misses some reports
            lat, lon = f.lat + rng.gauss(0, 0.0002), f.lon
            if device != OTHER and rng.random() < 0.05:
                lat += rng.choice((-1, 1)) * rng.uniform(0.01, 0.05)  # a spike, 1 to 5 km
            if device != OTHER and k in shared:
                lat += shared[k]
            if device == "BAG" and 60 <= k < 75:
                lat += 0.03  # the bag goes somewhere alone for a while
            t = f.t + timedelta(seconds=rng.uniform(0, 50))
            ob = make_observation(device_id=device, lat=lat, lon=lon, observed_at=t, accuracy=f.acc)
            out.append((t + timedelta(minutes=rng.choice(LAGS_MIN)), device, ob))
    return out


def _snapshot(session) -> list[tuple]:
    return sorted(
        (r.observation_id, r.score, r.suspect, r.reasons, r.corroborated_by)
        for r in session.scalars(select(ObservationQuality))
    )


@pytest.mark.parametrize("seed", [3, 11])
def test_incremental_equals_full_recompute(session, seed: int) -> None:
    for device in (*KID, OTHER):
        add_tracker(session, device)
    create_group(session, name="Kid", kind="person", member_ids=list(KID))
    polls: dict[tuple, list] = {}
    for fetched, device, ob in _sightings(seed):
        tick = fetched.replace(second=0, microsecond=0) + timedelta(minutes=3 - fetched.minute % 3)
        polls.setdefault((tick, device), []).append(ob)
    last_tick = None
    for (tick, _device), batch in sorted(polls.items()):
        if last_tick is not None and tick != last_tick:
            release_held_fixes(session, now=last_tick)  # the poller's end-of-cycle tick
        ingest_observations(session, batch, fetched_at=tick)
        last_tick = tick
    end = last_tick + timedelta(days=1)
    release_held_fixes(session, now=end)
    session.flush()
    incremental = _snapshot(session)
    assert any(row[2] for row in incremental), "the stream should contain suspects"
    session.execute(delete(ObservationQuality))
    store.recompute(session, now=end)
    session.flush()
    assert _snapshot(session) == incremental


def test_a_late_sibling_sighting_rescues_a_quiet_trackers_spike(session) -> None:
    """The watch's report reaches us hours late; the bag has said nothing since."""
    from tests.quality._ingest import at, obs, verdict

    for device in KID:
        add_tracker(session, device)
    create_group(session, name="Kid", kind="person", member_ids=list(KID))
    for minutes, north in ((0, 0), (3, 2000), (6, 30)):
        ingest_observations(session, [obs("BAG", minutes, north)], fetched_at=at(minutes + 0.5))
    assert verdict(session, "BAG", 3).suspect
    late = at(4) + timedelta(hours=3)
    ingest_observations(session, [obs("WATCH", 4, 2020)], fetched_at=late)
    assert not verdict(session, "BAG", 3).suspect
    assert verdict(session, "BAG", 3).corroborated_by is not None

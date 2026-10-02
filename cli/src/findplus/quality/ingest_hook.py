"""Ingest-time scoring and the geofence hold (spec section 6.3).

Purpose    : After a batch is inserted, rescore what the new fixes can change
             (the tracker's own fixes around them, its person-group siblings'
             fixes near them, and every fix still held), decide which fixes the
             geofence may see, and release the ones that were held back.
Inputs     : The session, the newly inserted rows, and `now` (the fetch time).
Outputs    : The observations to feed the geofence, in time order.
Constraints: A fix that is suspect when first scored is not fed. Whenever a
             rescore flips a stored verdict from suspect to clean, whatever the
             reason was, that fix is fed then (in observed order, ahead of the
             fixes that cleared it), so the ENTER carries its own time. A held
             fix with no next fix is released by `release_due` once its hold
             runs out; the poller calls it every cycle, so a quiet tracker is
             not stuck waiting for an ingest. Rows are rewritten only when the
             verdict changed. Raw rows are untouched; only `observation_quality`
             is written. A fix that was fed, later flagged and then cleared
             again would be fed twice; the geofence ignores fixes older than its
             last crossing, so the effect is at most one extra streak count.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select, true
from sqlalchemy.orm import Session, aliased

from findplus.db.models import LocationObservation
from findplus.db.models_people import ObservationQuality
from findplus.quality import store

#: Own fixes this far either side of a new fix are rescored: every rule reaches at
#: most 90 minutes (sibling "before") plus 15 (rescue) from the fix it judges.
OWN_PAD = timedelta(hours=2)
#: Sibling trackers' fixes this far either side are rescored (sibling window 10
#: minutes, plus the 15 minute rescue a cleared sibling fix can give its neighbours).
SIBLING_PAD = timedelta(minutes=30)

Span = tuple[datetime, datetime]


def held_by_device(session: Session, exclude: Iterable[int] = ()) -> dict[str, list[datetime]]:
    """device id -> observed times of suspect fixes still waiting on a next fix.

    A fix waits while no newer fix of the same tracker exists; fixes in
    `exclude` (the batch being ingested) do not count as newer, so the batch's
    own rescore decides them.
    """
    later = aliased(LocationObservation)
    skip = list(exclude)
    newer = exists().where(
        later.device_id == LocationObservation.device_id,
        later.observed_at > LocationObservation.observed_at,
        later.id.notin_(skip) if skip else true(),
    )
    rows = session.execute(
        select(LocationObservation.device_id, LocationObservation.observed_at)
        .join(ObservationQuality, ObservationQuality.observation_id == LocationObservation.id)
        .where(ObservationQuality.suspect.is_(True), ~newer)
    )
    out: dict[str, list[datetime]] = defaultdict(list)
    for device_id, observed_at in rows:
        out[device_id].append(observed_at)
    return out


def _merge(spans: list[Span]) -> list[Span]:
    """Overlapping or touching spans merged, in time order."""
    out: list[Span] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _spans(
    session: Session, new_rows: list[LocationObservation], held: dict[str, list[datetime]]
) -> dict[str, list[Span]]:
    """device id -> the time spans whose verdicts this batch (or the clock) can change."""
    spans: dict[str, list[Span]] = defaultdict(list)
    for device_id, times in held.items():
        spans[device_id] += [(t, t) for t in times]
    siblings: dict[str, list[str]] = {}
    for row in new_rows:
        t = row.observed_at
        spans[row.device_id].append((t - OWN_PAD, t + OWN_PAD))
        if row.device_id not in siblings:
            siblings[row.device_id] = store.sibling_ids(session, row.device_id)
        for sib in siblings[row.device_id]:
            spans[sib].append((t - SIBLING_PAD, t + SIBLING_PAD))
    return {d: _merge(s) for d, s in spans.items()}


def rescore(
    session: Session,
    new_rows: list[LocationObservation],
    held: dict[str, list[datetime]],
    now: datetime,
) -> tuple[set[int], set[int]]:
    """Rescore every affected span; return (new suspect ids, released ids)."""
    new_ids = {r.id for r in new_rows}
    suspect_new: set[int] = set()
    released: set[int] = set()
    for device_id, spans in sorted(_spans(session, new_rows, held).items()):
        for start, end in spans:
            scored = store.score_window(session, device_id, start, end, now=now)
            released |= store.write_changes(session, scored.values(), now=now) - new_ids
            suspect_new |= {i for i, s in scored.items() if i in new_ids and s.suspect}
    return suspect_new, released


def _rows(session: Session, ids: set[int]) -> list[LocationObservation]:
    if not ids:
        return []
    return list(session.scalars(select(LocationObservation).where(LocationObservation.id.in_(ids))))


def plan_geofence_feed(
    session: Session, new_rows: list[LocationObservation], now: datetime | None = None
) -> list[LocationObservation]:
    """Score the batch and return the observations the geofence may evaluate, in order.

    New suspect fixes are left out; any earlier fix this rescore cleared is
    added back, so it reaches the geofence with its own observed time.
    """
    now = now or datetime.now(UTC)
    held = held_by_device(session, exclude=[r.id for r in new_rows])
    suspect_new, released = rescore(session, new_rows, held, now)
    feed = [r for r in new_rows if r.id not in suspect_new] + _rows(session, released)
    return sorted(feed, key=lambda o: (o.observed_at, o.id))


def release_due(session: Session, now: datetime | None = None) -> list[LocationObservation]:
    """Held fixes whose hold has run out (or that something else cleared), in order.

    The wall-clock half of the hold: the poller calls this every cycle so a
    tracker that goes quiet after a far fix still gets its ENTER, stamped with
    the fix's own observed time.
    """
    now = now or datetime.now(UTC)
    _, released = rescore(session, [], held_by_device(session), now)
    return sorted(_rows(session, released), key=lambda o: (o.observed_at, o.id))

"""Ingest-time scoring and the geofence hold (spec section 6.3).

Purpose    : After a batch is inserted, score each new fix and its neighbours,
             decide which fixes the geofence may see, and release fixes that an
             earlier poll held back.
Inputs     : The session, the newly inserted rows, and `now` (the fetch time).
Outputs    : The observations to feed the geofence, in time order.
Constraints: One poll of delay, on purpose. A fix that jumps far and fast with
             nothing after it (`jump_unconfirmed`) is held out of the geofence.
             The next fix either confirms it (it is released, in order, ahead of
             the new fix) or turns it into `aba_teleport` (it is never fed). A
             real fast trip therefore ENTERs a place one poll late. Held fixes
             too old to ever be confirmed are released on the next ingest.
             Raw rows are untouched; only `observation_quality` is written.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import LocationObservation
from findplus.db.models_people import ObservationQuality
from findplus.quality import store
from findplus.quality.rules import JUMP_UNCONFIRMED
from findplus.quality.score import Scored

#: Look this far either side of the new and held fixes when rescoring.
_SPAN_PAD = timedelta(hours=1)


def held_by_device(session: Session) -> dict[str, set[int]]:
    """device id -> ids of fixes currently held as an unconfirmed jump."""
    rows = session.execute(
        select(LocationObservation.device_id, ObservationQuality.observation_id)
        .join(LocationObservation, LocationObservation.id == ObservationQuality.observation_id)
        .where(
            ObservationQuality.suspect.is_(True),
            ObservationQuality.reasons.contains(JUMP_UNCONFIRMED),
        )
    )
    out: dict[str, set[int]] = defaultdict(set)
    for device_id, oid in rows:
        out[device_id].add(oid)
    return out


def _target_ids(ordered_ids: list[int], new_ids: set[int], held: set[int]) -> set[int]:
    """New fixes, their immediate neighbours, and anything held: the rows to rewrite."""
    out = set(held)
    for i, oid in enumerate(ordered_ids):
        if oid in new_ids:
            out.update(ordered_ids[max(0, i - 1) : i + 2])
    return out & set(ordered_ids)


def _rescore_device(
    session: Session, device_id: str, new_ids: set[int], held: set[int], now: datetime
) -> tuple[dict[int, Scored], set[int]]:
    """Rewrite verdicts around `new_ids`/`held`; return them and the ids released from hold."""
    marks = new_ids | held
    times = list(
        session.scalars(
            select(LocationObservation.observed_at).where(LocationObservation.id.in_(marks))
        )
    )
    if not times:
        return {}, set()
    fixes, scored = store.score_context(
        session, device_id, min(times) - _SPAN_PAD, max(times) + _SPAN_PAD, now=now
    )
    targets = _target_ids([f.id for f in fixes], new_ids, held)
    chosen = {i: scored[i] for i in targets}
    released = {i for i in held if i in chosen and not chosen[i].suspect}
    store.write_scores(session, chosen.values(), now=now)
    return chosen, released


def plan_geofence_feed(
    session: Session, new_rows: list[LocationObservation], now: datetime | None = None
) -> list[LocationObservation]:
    """Score the batch and return the observations the geofence may evaluate, in order.

    New suspect fixes are left out; fixes held by an earlier poll that are now
    cleared are added back (in time order, ahead of the fixes that cleared them).
    """
    now = now or datetime.now(UTC)
    held = held_by_device(session)
    new_by_dev: dict[str, set[int]] = defaultdict(set)
    for row in new_rows:
        new_by_dev[row.device_id].add(row.id)
    suspect_new: set[int] = set()
    released: set[int] = set()
    for device_id in sorted(set(new_by_dev) | set(held)):
        chosen, freed = _rescore_device(
            session, device_id, new_by_dev.get(device_id, set()), held.get(device_id, set()), now
        )
        suspect_new |= {
            i for i in new_by_dev.get(device_id, ()) if i in chosen and chosen[i].suspect
        }
        released |= freed
    feed = [r for r in new_rows if r.id not in suspect_new]
    if released:
        feed += list(
            session.scalars(select(LocationObservation).where(LocationObservation.id.in_(released)))
        )
    return sorted(feed, key=lambda o: (o.observed_at, o.id))

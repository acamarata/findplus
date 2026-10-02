"""Read and write `observation_quality`; recompute it from raw observations.

Purpose    : The DB half of quality: load a tracker's fixes (and its siblings'),
             score them with `quality.score`, and upsert the verdict rows.
Inputs     : A session; a device id and time window, or a `since` date.
Outputs    : `ObservationQuality` rows and small result dataclasses.
Constraints: Raw observations never change (invariant 8): only the derived row is
             written. Rows carry `algo_version`; `recompute` rewrites every row
             in range, so a version bump is one command. Never commits (the
             caller owns the transaction) unless `recompute(commit_every=N)`
             is asked to: then it commits every N rows so a long run never
             holds the write lock for more than a moment. Siblings are the other trackers of
             the same person or pet group.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Device, DeviceGroup, Group, LocationObservation
from findplus.db.models_people import PERSON_KINDS, ObservationQuality
from findplus.quality.fix import Fix
from findplus.quality.rules import ALGO_VERSION
from findplus.quality.score import Scored, score_series

#: How far around a window the scorer looks for neighbours and siblings.
CONTEXT_PAD = timedelta(hours=3)


def to_fix(row: LocationObservation) -> Fix:
    """A scoring `Fix` from a stored observation."""
    return Fix(
        row.id,
        row.observed_at,
        row.latitude,
        row.longitude,
        row.accuracy_meters,
        row.first_fetched_at,
        bool(row.is_own_report) or row.source == "own_report",
    )


def load_fixes(session: Session, device_id: str, start: datetime, end: datetime) -> list[Fix]:
    """Time-ordered fixes of one tracker with observed_at in [start, end]."""
    rows = session.scalars(
        select(LocationObservation)
        .where(
            LocationObservation.device_id == device_id,
            LocationObservation.observed_at >= start,
            LocationObservation.observed_at <= end,
        )
        .order_by(LocationObservation.observed_at, LocationObservation.id)
    )
    return [to_fix(r) for r in rows]


def sibling_ids(session: Session, device_id: str) -> list[str]:
    """Other trackers that share a person or pet group with `device_id`."""
    groups = select(DeviceGroup.group_id).where(DeviceGroup.device_id == device_id)
    stmt = (
        select(DeviceGroup.device_id)
        .join(Group, Group.id == DeviceGroup.group_id)
        .where(
            DeviceGroup.group_id.in_(groups),
            Group.kind.in_(PERSON_KINDS),
            DeviceGroup.device_id != device_id,
        )
        .distinct()
    )
    return sorted(session.scalars(stmt))


def load_siblings(
    session: Session, device_id: str, start: datetime, end: datetime
) -> dict[str, list[Fix]]:
    """Each sibling tracker's fixes in the window (empty when it has none)."""
    out = {s: load_fixes(session, s, start, end) for s in sibling_ids(session, device_id)}
    return {k: v for k, v in out.items() if v}


def write_scores(session: Session, scored: Iterable[Scored], *, now: datetime | None = None) -> int:
    """Upsert verdict rows (stamped with the current algo version); returns the count."""
    stamp = now or datetime.now(UTC)
    items = list(scored)
    for i in range(0, len(items), 500):
        chunk = items[i : i + 500]
        existing = {
            row.observation_id: row
            for row in session.scalars(
                select(ObservationQuality).where(
                    ObservationQuality.observation_id.in_([s.observation_id for s in chunk])
                )
            )
        }
        for s in chunk:
            row = existing.get(s.observation_id)
            if row is None:
                row = ObservationQuality(observation_id=s.observation_id)
                session.add(row)
            row.score = s.score
            row.suspect = s.suspect
            row.reasons = ",".join(s.reasons)
            row.corroborated_by = s.corroborated_by
            row.algo_version = ALGO_VERSION
            row.computed_at = stamp
    session.flush()
    return len(items)


def _differs(row: ObservationQuality, s: Scored) -> bool:
    return (
        row.score != s.score
        or bool(row.suspect) != s.suspect
        or row.reasons != ",".join(s.reasons)
        or row.corroborated_by != s.corroborated_by
        or row.algo_version != ALGO_VERSION
    )


def write_changes(
    session: Session, scored: Iterable[Scored], *, now: datetime | None = None
) -> set[int]:
    """Upsert only verdicts that are new or changed; return ids that went suspect -> clean.

    The ingest hook feeds those ids to the geofence: a fix it once held back
    has just been cleared. Unchanged rows keep their `computed_at`.
    """
    items = list(scored)
    released: set[int] = set()
    changed: list[Scored] = []
    for i in range(0, len(items), 500):
        chunk = items[i : i + 500]
        ids = [s.observation_id for s in chunk]
        rows = session.scalars(
            select(ObservationQuality).where(ObservationQuality.observation_id.in_(ids))
        )
        existing = {row.observation_id: row for row in rows}
        for s in chunk:
            row = existing.get(s.observation_id)
            if row is not None and row.suspect and not s.suspect:
                released.add(s.observation_id)
            if row is None or _differs(row, s):
                changed.append(s)
    write_scores(session, changed, now=now)
    return released


def score_context(
    session: Session,
    device_id: str,
    start: datetime,
    end: datetime,
    *,
    now: datetime | None = None,
    pad: timedelta = CONTEXT_PAD,
) -> tuple[list[Fix], dict[int, Scored]]:
    """(fixes in [start, end] in time order, their verdicts), scored with `pad` of context.

    The padding exists so edge fixes see their neighbours and siblings; nothing
    outside the window is returned and nothing is written.
    """
    fixes = load_fixes(session, device_id, start - pad, end + pad)
    sibs = load_siblings(session, device_id, start - pad, end + pad)
    scored = score_series(fixes, siblings=sibs, now=now)
    inside = [f for f in fixes if start <= f.t <= end]
    return inside, {f.id: scored[f.id] for f in inside}


def score_window(
    session: Session,
    device_id: str,
    start: datetime,
    end: datetime,
    *,
    now: datetime | None = None,
    pad: timedelta = CONTEXT_PAD,
) -> dict[int, Scored]:
    """Verdicts for `device_id`'s fixes in [start, end]; see `score_context`."""
    return score_context(session, device_id, start, end, now=now, pad=pad)[1]


def verdicts_for(session: Session, ids: Sequence[int]) -> dict[int, tuple[bool, tuple[str, ...]]]:
    """Stored (suspect, reasons) for the given observation ids; ids with no row are absent."""
    out: dict[int, tuple[bool, tuple[str, ...]]] = {}
    for i in range(0, len(ids), 500):
        rows = session.execute(
            select(
                ObservationQuality.observation_id,
                ObservationQuality.suspect,
                ObservationQuality.reasons,
            ).where(ObservationQuality.observation_id.in_(ids[i : i + 500]))
        )
        for oid, suspect, reasons in rows:
            out[oid] = (bool(suspect), tuple(c for c in reasons.split(",") if c))
    return out


@dataclass(frozen=True, slots=True)
class RecomputeResult:
    """What `recompute` did."""

    devices: int
    rows: int
    suspects: int


def recompute(
    session: Session,
    *,
    since: datetime | None = None,
    now: datetime | None = None,
    commit_every: int = 0,
) -> RecomputeResult:
    """Rewrite quality rows for every tracker (from `since`, or all history).

    With `commit_every` > 0 the writes go out in chunks of that many rows, each
    committed, so another writer (the poller) is never locked out for the whole run.
    """
    now = now or datetime.now(UTC)
    start = since or datetime(1970, 1, 1, tzinfo=UTC)
    end = now + timedelta(days=1)
    devices = list(session.scalars(select(Device.device_id).order_by(Device.device_id)))
    rows = suspects = 0
    for device_id in devices:
        scored = score_window(session, device_id, start, end, now=now)
        values = list(scored.values())
        step = commit_every if commit_every > 0 else max(len(values), 1)
        for i in range(0, len(values), step):
            rows += write_scores(session, values[i : i + step], now=now)
            if commit_every > 0:
                session.commit()
                session.expunge_all()
        suspects += sum(1 for s in scored.values() if s.suspect)
    return RecomputeResult(len(devices), rows, suspects)

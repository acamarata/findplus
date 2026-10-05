"""Rebuild the derived state tables from the raw sightings.

Purpose    : `findplus db rebuild-derived`: after an import (or any time the
             derived tables look wrong) replay every sighting, oldest first,
             through the same geofence, group and person engines the poller uses.
Inputs     : An open session, Settings.
Outputs    : `RebuildResult` with what was replayed and rebuilt.
Constraints: Raw sightings are only read. The derived tables (place states and
             events, group place events, person place states, left-behind
             episodes) are emptied and rebuilt; a left-behind episode the owner
             dismissed is therefore forgotten. Every rebuilt event is stamped
             `notified_at` before it is committed, so the alert dispatcher never
             sends it: a rebuild must not message anyone about the past. Alert
             deliveries and digest runs are not touched. Commits every
             `chunk` (200) sightings so other writers get in between (but run it
             with the daemon stopped). Sightings that look wrong are skipped,
             as live ingest skips them. Each chunk runs in `BEGIN IMMEDIATE`:
             it holds SQLite's write lock from its first read, so a commit from
             another connection cannot strand it on a stale snapshot ("database
             is locked", which busy_timeout cannot wait out). A chunk that still
             meets a lock is rolled back and replayed; a hook that fails for any
             other reason is logged and counted in `RebuildResult.failed`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from findplus.db.models import (
    GroupPlaceEvent,
    LocationObservation,
    PlaceEvent,
    PlaceState,
)
from findplus.db.models_people import LeftBehind, PersonPlaceState
from findplus.groups.events import evaluate_group_events
from findplus.logging_setup import get_logger
from findplus.people.events import run_person_hook
from findplus.places.events import evaluate as geofence_evaluate

log = get_logger(__name__)

_DERIVED = (PersonPlaceState, LeftBehind, GroupPlaceEvent, PlaceEvent, PlaceState)
_EVENTS = (PlaceEvent, GroupPlaceEvent, LeftBehind)
#: Tries per chunk when SQLite reports the database locked (each waits busy_timeout first).
_LOCK_TRIES = 5


@dataclass(frozen=True, slots=True)
class RebuildResult:
    """What a rebuild did."""

    observations: int
    place_events: int
    group_events: int
    left_behind: int
    #: Hook runs that raised (logged as rebuild_hook_failed); their events are missing.
    failed: int = 0


def _count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _is_locked(exc: BaseException) -> bool:
    text = str(getattr(exc, "orig", exc)).lower()
    return isinstance(exc, OperationalError) and ("locked" in text or "busy" in text)


def _replay_one(session: Session, lo: LocationObservation, settings) -> int:
    """The three live hooks for one sighting, each in its own savepoint.

    Returns how many hooks failed. A lock error is raised instead, so the whole
    chunk is rolled back and replayed rather than losing this sighting's events.
    """

    def geofence() -> None:
        geofence_evaluate(session, lo, default_accuracy=settings.geofence_default_accuracy_meters)

    def groups() -> None:
        stmt = select(PlaceEvent).where(PlaceEvent.observation_id == lo.id)
        for event in session.scalars(stmt).all():
            evaluate_group_events(session, event, settings, now=lo.observed_at)

    def people() -> None:
        run_person_hook(session, lo, settings)

    failed = 0
    for name, hook in (("geofence", geofence), ("group_events", groups), ("person_events", people)):
        try:
            with session.begin_nested():
                hook()
        except Exception as exc:
            if _is_locked(exc):
                raise
            log.exception("rebuild_hook_failed", hook=name, observation_id=lo.id)
            failed += 1
    return failed


def _begin_immediate(session: Session) -> None:
    """Open the session's transaction with SQLite's write lock already held.

    pysqlite only opens a transaction lazily, so the first statement sent here
    is the BEGIN. busy_timeout applies to it, unlike a later read-to-write upgrade.
    """
    conn = session.connection()
    if conn.dialect.name == "sqlite" and not conn.connection.driver_connection.in_transaction:
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def _locked_unit[T](session: Session, work: Callable[[], T]) -> T:
    """Run `work` in one write-locked transaction and commit; retry it on a lock."""
    for attempt in range(1, _LOCK_TRIES + 1):
        try:
            _begin_immediate(session)
            out = work()
            session.commit()
            return out
        except OperationalError as exc:
            session.rollback()
            if not _is_locked(exc) or attempt == _LOCK_TRIES:
                raise
            log.warning("rebuild_locked_retry", attempt=attempt)
            time.sleep(0.1 * 2**attempt)
    raise AssertionError("unreachable")


def _suspect(session: Session, lo: LocationObservation) -> bool:
    from findplus.people._quality import is_suspect

    return is_suspect(session, lo.id)


def _stamp_notified(session: Session, now: datetime) -> None:
    for model in _EVENTS:
        session.execute(update(model).where(model.notified_at.is_(None)).values(notified_at=now))


def _replay_chunk(
    session: Session, settings, cursor: tuple[datetime, int], chunk: int, now: datetime
) -> tuple[list[LocationObservation], int]:
    """The next `chunk` sightings after `cursor`, replayed; returns them and the failed hooks."""
    key = tuple_(LocationObservation.observed_at, LocationObservation.id)
    rows = session.scalars(
        select(LocationObservation)
        .where(key > tuple_(*cursor))
        .order_by(LocationObservation.observed_at, LocationObservation.id)
        .limit(chunk)
    ).all()
    bad = sum(_replay_one(session, lo, settings) for lo in rows if not _suspect(session, lo))
    _stamp_notified(session, now)
    return list(rows), bad


def rebuild_derived(
    session: Session, settings, *, chunk: int = 200, now: datetime | None = None, progress=None
) -> RebuildResult:
    """Empty the derived tables and replay every sighting through the engines.

    `progress(done, total)` is called after every chunk (people/replay.py's status).
    """
    now = now or datetime.now(UTC)

    def empty() -> int:
        for model in _DERIVED:
            session.execute(delete(model))
        return _count(session, LocationObservation)

    total = _locked_unit(session, empty)
    cursor = (datetime.min.replace(tzinfo=UTC), 0)
    replayed = failed = 0

    while True:
        replay = partial(_replay_chunk, session, settings, cursor, chunk, now)
        rows, chunk_failed = _locked_unit(session, replay)
        if not rows:
            break
        replayed += len(rows)
        failed += chunk_failed
        if progress is not None:
            progress(replayed, total)
        cursor = (rows[-1].observed_at, rows[-1].id)
        session.expunge_all()
    if failed:
        log.warning("rebuild_incomplete", failed=failed, observations=replayed)
    return RebuildResult(
        replayed,
        _count(session, PlaceEvent),
        _count(session, GroupPlaceEvent),
        _count(session, LeftBehind),
        failed,
    )

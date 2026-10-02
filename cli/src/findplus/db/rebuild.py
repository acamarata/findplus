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
             `chunk` sightings so the poller can write in between (but run it
             with the daemon stopped). Sightings that look wrong are skipped,
             as live ingest skips them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, tuple_, update
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


@dataclass(frozen=True, slots=True)
class RebuildResult:
    """What a rebuild did."""

    observations: int
    place_events: int
    group_events: int
    left_behind: int


def _count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _replay_one(session: Session, lo: LocationObservation, settings) -> None:
    """The three live hooks for one sighting, each in its own savepoint."""

    def geofence() -> None:
        geofence_evaluate(session, lo, default_accuracy=settings.geofence_default_accuracy_meters)

    def groups() -> None:
        stmt = select(PlaceEvent).where(PlaceEvent.observation_id == lo.id)
        for event in session.scalars(stmt).all():
            evaluate_group_events(session, event, settings, now=lo.observed_at)

    def people() -> None:
        run_person_hook(session, lo, settings)

    for name, hook in (("geofence", geofence), ("group_events", groups), ("person_events", people)):
        try:
            with session.begin_nested():
                hook()
        except Exception:
            log.exception("rebuild_hook_failed", hook=name, observation_id=lo.id)


def _suspect(session: Session, lo: LocationObservation) -> bool:
    from findplus.people._quality import is_suspect

    return is_suspect(session, lo.id)


def _stamp_notified(session: Session, now: datetime) -> None:
    for model in _EVENTS:
        session.execute(update(model).where(model.notified_at.is_(None)).values(notified_at=now))


def rebuild_derived(
    session: Session, settings, *, chunk: int = 500, now: datetime | None = None
) -> RebuildResult:
    """Empty the derived tables and replay every sighting through the engines."""
    now = now or datetime.now(UTC)
    for model in _DERIVED:
        session.execute(delete(model))
    session.commit()
    cursor = (datetime.min.replace(tzinfo=UTC), 0)
    replayed = 0
    while True:
        key = tuple_(LocationObservation.observed_at, LocationObservation.id)
        rows = session.scalars(
            select(LocationObservation)
            .where(key > tuple_(*cursor))
            .order_by(LocationObservation.observed_at, LocationObservation.id)
            .limit(chunk)
        ).all()
        if not rows:
            break
        for lo in rows:
            if not _suspect(session, lo):
                _replay_one(session, lo, settings)
            replayed += 1
        _stamp_notified(session, now)
        session.commit()
        cursor = (rows[-1].observed_at, rows[-1].id)
        session.expunge_all()
    return RebuildResult(
        replayed,
        _count(session, PlaceEvent),
        _count(session, GroupPlaceEvent),
        _count(session, LeftBehind),
    )

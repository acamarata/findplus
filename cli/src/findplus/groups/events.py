"""Ingest-time group quorum hook: emit group_place_events so group rules can fire.

Purpose : Turn one device's just-committed place_event into zero or more
          group_place_events rows, so group alert rules (E9) have real data to
          match against. Before this module nothing wrote group_place_events at
          all (E6 CR-C finding) -- group rules could never fire in production.
Inputs  : plan_group_events (pure) takes GroupCandidate rows built from the DB.
          evaluate_group_events(session, place_event, settings) does the DB
          read, delegates the fire/no-fire decision to
          findplus.groups.quorum.evaluate_quorum, and persists.
Outputs : list[GroupPlaceEvent] -- the ORM rows this call inserted (empty when
          nothing fired). Dispatch is not called directly: the row is written
          with notified_at=None, so poller.py's existing post-commit
          `dispatch.process(dispatch.load_pending_events(session), ...)` picks
          it up the same way it already picks up device place_events -- no
          alerts-module change needed.
Constraints: Never raising past the caller is the CALLER's job (ingest.py
          wraps this the same way it wraps the geofence hook, in its own
          SAVEPOINT). A naive `now` raises ValueError.
Reuse: findplus.groups.quorum.{QuorumInput,evaluate_quorum} (D19 quorum math);
       DeviceGroup/Group/GroupPlaceEvent/PlaceEvent models already used by
       groups/repo.py and places/events.py; the SAVEPOINT-per-hook pattern in
       ingest.py's `_run_post_ingest_hooks`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import (
    DeviceGroup,
    Group,
    GroupPlaceEvent,
    LocationObservation,
    PlaceEvent,
)
from findplus.groups.quorum import QuorumInput, QuorumResult, evaluate_quorum
from findplus.logging_setup import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class GroupCandidate:
    """One group the triggering device belongs to, ready for evaluate_quorum."""

    group_id: int
    quorum: str
    member_ids: list[str]
    stale_ids: list[str]
    place_id: int
    event_type: str
    window_minutes: int
    member_events: list[tuple[str, int, datetime]]


def plan_group_events(candidates: list[GroupCandidate], now: datetime) -> dict[int, QuorumResult]:
    """Pure: run evaluate_quorum per candidate group. Returns firing results by group_id."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    fired: dict[int, QuorumResult] = {}
    for c in candidates:
        result = evaluate_quorum(
            QuorumInput(
                group_id=c.group_id,
                quorum=c.quorum,
                member_ids=c.member_ids,
                stale_ids=c.stale_ids,
                place_id=c.place_id,
                event_type=c.event_type,
                window_minutes=c.window_minutes,
                member_events=c.member_events,
            )
        )
        if result.fire:
            fired[c.group_id] = result
    return fired


def _stale_member_ids(
    session: Session, member_ids: list[str], now: datetime, presence_window_minutes: int
) -> list[str]:
    """Members whose most recent observation is older than the presence window (or absent)."""
    cutoff = now - timedelta(minutes=presence_window_minutes)
    stale: list[str] = []
    for device_id in member_ids:
        last_seen = session.scalar(
            select(LocationObservation.observed_at)
            .where(LocationObservation.device_id == device_id)
            .order_by(LocationObservation.observed_at.desc())
            .limit(1)
        )
        if last_seen is None or last_seen < cutoff:
            stale.append(device_id)
    return stale


def _member_events_in_window(
    session: Session,
    member_ids: list[str],
    place_id: int,
    event_type: str,
    center: datetime,
    window_minutes: int,
) -> list[tuple[str, int, datetime]]:
    """(device_id, place_event_id, observed_at) for members crossing near `center`."""
    lo, hi = center - timedelta(minutes=window_minutes), center + timedelta(minutes=window_minutes)
    rows = session.execute(
        select(PlaceEvent.device_id, PlaceEvent.id, PlaceEvent.observed_at).where(
            PlaceEvent.place_id == place_id,
            PlaceEvent.event_type == event_type,
            PlaceEvent.device_id.in_(member_ids),
            PlaceEvent.observed_at >= lo,
            PlaceEvent.observed_at <= hi,
        )
    ).all()
    return [(r.device_id, r.id, r.observed_at) for r in rows]


def _existing_group_event(
    session: Session,
    group_id: int,
    place_id: int,
    event_type: str,
    center: datetime,
    window_minutes: int,
) -> GroupPlaceEvent | None:
    """A group_place_events row already covering this (group, place, type, window)."""
    lo, hi = center - timedelta(minutes=window_minutes), center + timedelta(minutes=window_minutes)
    return session.scalar(
        select(GroupPlaceEvent).where(
            GroupPlaceEvent.group_id == group_id,
            GroupPlaceEvent.place_id == place_id,
            GroupPlaceEvent.event_type == event_type,
            GroupPlaceEvent.observed_at >= lo,
            GroupPlaceEvent.observed_at <= hi,
        )
    )


def _build_candidate(
    session: Session,
    group: Group,
    place_event: PlaceEvent,
    now: datetime,
    presence_window_minutes: int,
    group_window_minutes: int,
) -> GroupCandidate:
    member_ids = list(
        session.scalars(select(DeviceGroup.device_id).where(DeviceGroup.group_id == group.id)).all()
    )
    stale_ids = _stale_member_ids(session, member_ids, now, presence_window_minutes)
    member_events = _member_events_in_window(
        session,
        member_ids,
        place_event.place_id,
        place_event.event_type,
        place_event.observed_at,
        group_window_minutes,
    )
    return GroupCandidate(
        group_id=group.id,
        quorum=group.quorum,
        member_ids=member_ids,
        stale_ids=stale_ids,
        place_id=place_event.place_id,
        event_type=place_event.event_type,
        window_minutes=group_window_minutes,
        member_events=member_events,
    )


def _persist_fired(
    session: Session,
    groups: list[Group],
    fired: dict[int, QuorumResult],
    place_event: PlaceEvent,
    group_window_minutes: int,
) -> list[GroupPlaceEvent]:
    """Insert one group_place_events row per firing group, skipping window duplicates."""
    inserted: list[GroupPlaceEvent] = []
    for group in groups:
        result = fired.get(group.id)
        if result is None:
            continue
        if _existing_group_event(
            session,
            group.id,
            place_event.place_id,
            place_event.event_type,
            place_event.observed_at,
            group_window_minutes,
        ):
            continue
        row = GroupPlaceEvent(
            group_id=group.id,
            place_id=place_event.place_id,
            event_type=place_event.event_type,
            observed_at=result.observed_at,
            member_event_ids=json.dumps(result.member_event_ids),
            members_crossed=result.members_crossed,
            members_considered=result.members_considered,
            members_stale=result.members_stale,
            confidence=result.confidence,
            notified_at=None,
        )
        session.add(row)
        inserted.append(row)
        log.info(
            "group_place_event",
            group_id=group.id,
            place_id=place_event.place_id,
            event_type=place_event.event_type,
            members_crossed=result.members_crossed,
            members_considered=result.members_considered,
        )
    return inserted


def evaluate_group_events(
    session: Session,
    place_event: PlaceEvent,
    settings: object,
    *,
    now: datetime | None = None,
) -> list[GroupPlaceEvent]:
    """Fire this device's groups' quorum rules for `place_event`, insert rows, return them.

    A group whose window already has a group_place_events row for the same
    (group_id, place_id, event_type) is skipped -- a second member crossing
    inside the same window must not create a second row. `now` defaults to the
    wall clock (matches `alerts.dispatch.process`'s own override hook); tests
    pass a fixed value so staleness checks are deterministic.
    """
    group_window = settings.group_window_minutes
    presence_window = settings.presence_window_minutes
    now = now or datetime.now(UTC)

    group_ids = list(
        session.scalars(
            select(DeviceGroup.group_id).where(DeviceGroup.device_id == place_event.device_id)
        ).all()
    )
    if not group_ids:
        return []
    groups = list(session.scalars(select(Group).where(Group.id.in_(group_ids))).all())

    candidates = [
        _build_candidate(session, g, place_event, now, presence_window, group_window)
        for g in groups
    ]
    fired = plan_group_events(candidates, now)
    inserted = _persist_fired(session, groups, fired, place_event, group_window)
    if inserted:
        session.flush()
    return inserted

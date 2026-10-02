"""Person arrived/left events: one row per person crossing (spec § 5.1).

Purpose : After geofence and the group hook, re-infer each person the new
          sighting's tracker belongs to and move person_place_states. A
          transition writes ONE group_place_events row (basis='person') that the
          existing dispatch picks up, so four trackers crossing Grandma's
          together produce one message, not four.
Inputs  : The just-inserted LocationObservation; Settings (unused today, kept
          for the hook signature ingest.py shares).
Outputs : The GroupPlaceEvent rows inserted (also evaluates left-behind).
Constraints: Never commits; ingest.py runs this in its own SAVEPOINT. Suspect
          sightings are skipped. An observation at or before a state's
          since_observed_at never moves it (late reports cannot rewrite the
          past). `unsure` never moves state. First evaluation seeds silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import GroupPlaceEvent, LocationObservation, PlaceEvent, PlaceState
from findplus.db.models_people import PersonPlaceState
from findplus.groups.events import _existing_group_event, _insert_group_event
from findplus.logging_setup import get_logger
from findplus.people import _quality, left_behind
from findplus.people.infer import PersonFix
from findplus.people.inputs import infer_person, person_groups_of
from findplus.people.notes import event_note

log = get_logger(__name__)

#: An opposite transition at the same place waits this long after the last one.
SETTLE_MINUTES = 10


@dataclass(frozen=True)
class Step:
    state: str
    pending_side: str | None
    pending_since: datetime | None
    last_transition_at: datetime | None
    event_type: str | None


def person_target(fix: PersonFix, place_id: int, states: dict[tuple[str, int], str]) -> str | None:
    """inside / outside / None (no change) for one place (spec § 5.1 step 3)."""
    if fix.confidence not in ("likely", "probably") or not fix.supporters:
        return None
    sides = [states.get((d, place_id), "unknown") for d in fix.supporters]
    if "inside" in sides:
        return "inside"
    if "outside" in sides:
        return "outside"
    return None


def step(
    state: str,
    pending_side: str | None,
    pending_since: datetime | None,
    last_transition_at: datetime | None,
    target: str | None,
    as_of: datetime,
    settle_minutes: int = SETTLE_MINUTES,
) -> Step:
    """Advance one (person, place) state by one evaluation. Pure."""
    if target is None:
        return Step(state, pending_side, pending_since, last_transition_at, None)
    if state == "unknown":
        return Step(target, None, None, last_transition_at, None)  # seed, no event (D17)
    if target == state:
        return Step(state, None, None, last_transition_at, None)
    if last_transition_at is not None and as_of - last_transition_at < timedelta(
        minutes=settle_minutes
    ):
        return Step(state, target, pending_since or as_of, last_transition_at, None)
    event = "ENTER" if target == "inside" else "EXIT"
    return Step(target, None, None, as_of, event)


def _device_states(session: Session, device_ids: list[str]) -> dict[tuple[str, int], str]:
    rows = session.execute(
        select(PlaceState.device_id, PlaceState.place_id, PlaceState.state).where(
            PlaceState.device_id.in_(device_ids)
        )
    ).all()
    return {(r.device_id, r.place_id): r.state for r in rows}


def _member_event_ids(session, fix: PersonFix, place_id: int, event_type: str, as_of) -> list[int]:
    lo = as_of - timedelta(hours=6)
    return list(
        session.scalars(
            select(PlaceEvent.id)
            .where(
                PlaceEvent.place_id == place_id,
                PlaceEvent.event_type == event_type,
                PlaceEvent.device_id.in_(list(fix.supporters)),
                PlaceEvent.observed_at >= lo,
                PlaceEvent.observed_at <= as_of,
            )
            .order_by(PlaceEvent.observed_at)
        ).all()
    )


def _write_event(session, group, place, fix, trackers, states, event_type, as_of):
    """Insert the one person row for this crossing, unless one already covers it."""
    if _existing_group_event(session, group.id, place.id, event_type, as_of, SETTLE_MINUTES):
        return None
    ids = _member_event_ids(session, fix, place.id, event_type, as_of)
    side = "inside" if event_type == "ENTER" else "outside"
    crossed = sum(1 for d in fix.supporters if states.get((d, place.id)) == side)
    row = GroupPlaceEvent(
        group_id=group.id,
        place_id=place.id,
        event_type=event_type,
        observed_at=as_of,
        member_event_ids=json.dumps(ids),
        members_crossed=crossed,
        members_considered=len(trackers) - len(fix.stale),
        members_stale=len(fix.stale),
        confidence="high" if fix.confidence == "likely" else "medium",
        notified_at=None,
        basis="person",
        note=event_note(group, place, fix, trackers, states, event_type),
        lead_device_id=fix.lead_device_id,
    )
    return row if _insert_group_event(session, row) else None


def evaluate_person(session: Session, group, as_of: datetime) -> list[GroupPlaceEvent]:
    """Re-infer one person as of `as_of` and move every place's state."""
    fix, trackers, places = infer_person(session, group, as_of)
    states = _device_states(session, [t.device_id for t in trackers])
    now = datetime.now(UTC)
    inserted: list[GroupPlaceEvent] = []
    for place in places:
        row = session.get(PersonPlaceState, (group.id, place.id))
        if row is not None and row.since_observed_at and as_of <= row.since_observed_at:
            continue  # backfill guard: a late older report never moves the state
        if row is None:
            row = PersonPlaceState(group_id=group.id, place_id=place.id, state="unknown")
            session.add(row)
        target = person_target(fix, place.id, states)
        s = step(row.state, row.pending_side, row.pending_since, row.last_transition_at,
                 target, as_of)  # fmt: skip
        row.state, row.pending_side, row.pending_since = s.state, s.pending_side, s.pending_since
        row.last_transition_at, row.since_observed_at, row.updated_at = (
            s.last_transition_at, as_of, now,
        )  # fmt: skip
        if s.event_type:
            event = _write_event(session, group, place, fix, trackers, states, s.event_type, as_of)
            if event is not None:
                inserted.append(event)
                log.info("person_place_event", group_id=group.id, place_id=place.id,
                         event_type=s.event_type, confidence=fix.confidence)  # fmt: skip
    session.flush()
    left_behind.evaluate(session, group, fix, trackers, places, as_of)
    return inserted


def run_person_hook(session: Session, observation: LocationObservation, settings: object = None):
    """The ingest hook: every person/pet this sighting's tracker belongs to."""
    if _quality.is_suspect(session, observation.id):
        return []
    inserted: list[GroupPlaceEvent] = []
    for group in person_groups_of(session, observation.device_id):
        inserted.extend(evaluate_person(session, group, observation.observed_at))
    return inserted

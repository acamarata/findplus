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
          sightings are skipped. An observation before a state's
          since_observed_at never moves it (late reports cannot rewrite the
          past); one at the same instant may (carried trackers report
          together, uat116 #2). `unsure` never moves state. First evaluation
          seeds silently. An arrival closes every place it cannot overlap. A
          state nothing has confirmed for 12 h becomes unknown first, so a
          tracker that died at School never produces a later "left School"
          (people/expiry.py).
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
from findplus.people.crossing import crossing, near
from findplus.people.expiry import expired
from findplus.people.infer import PersonFix, PlaceRef
from findplus.people.inputs import infer_person, person_groups_of
from findplus.people.notes import event_note

log = get_logger(__name__)

#: An opposite transition at the same place waits this long after the last one.
SETTLE_MINUTES = 10
#: Motion that may move person state on its own (people/motion.py).
_MOVING = ("carried", "unknown")


@dataclass(frozen=True)
class Step:
    state: str
    pending_side: str | None
    pending_since: datetime | None
    last_transition_at: datetime | None
    event_type: str | None


def qualified(fix: PersonFix, crossed: frozenset[str] | set[str] = frozenset()) -> bool:
    """May this answer move person state? Only when a supporter is being
    carried now (or is too new to judge), or crossed this place itself (a
    device ENTER/EXIT) since the last person transition. Trackers sitting
    still (parked, or settled after an earlier trip) cannot say the person
    came home while the one actually carried has gone quiet (r116 #1/#3)."""
    motion = {m.device_id: m.motion for m in fix.members}
    return any(motion.get(d) in _MOVING or d in crossed for d in fix.supporters)


def person_target(
    fix: PersonFix,
    place: PlaceRef,
    states: dict[tuple[str, int], str],
    crossed: frozenset[str] | set[str] = frozenset(),
    seeding: bool = False,
) -> str | None:
    """inside / outside / None (no change) for one place (spec § 5.1 step 3).

    "inside" also needs the supporter's own non-suspect sighting to be at the
    place: a device state set by a sighting the quality flags later threw out
    must not put the person there. `crossed` = supporters with a device-level
    ENTER/EXIT at this place since the person's last transition there. A first
    evaluation (`seeding`) may use parked trackers: it sets state without an event.
    """
    if fix.confidence not in ("likely", "probably") or not fix.supporters:
        return None
    if not seeding and not qualified(fix, crossed):
        return None  # hold: say "no recent sighting", never move on parked trackers
    last = {m.device_id: m.fix for m in fix.members}
    sides = [states.get((d, place.id), "unknown") for d in fix.supporters]
    if any(
        side == "inside" and near(place, last.get(d))
        for d, side in zip(fix.supporters, sides, strict=True)
    ):
        return "inside"
    if "inside" in sides:
        return None  # its own geofence has not confirmed the exit yet (D17: 2 fixes)
    return "outside" if "outside" in sides else None


def confirms(
    fix: PersonFix, place: PlaceRef, states, crossed, state: str, target: str | None
) -> bool:
    """Does this evaluation back the stored side? A move target does; so does
    parked evidence that says the same (a sleeping household), though it cannot move state."""
    if target is not None:
        return True
    return person_target(fix, place, states, crossed, seeding=True) == state


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


def _crossings(session, fix: PersonFix, as_of: datetime) -> list[tuple[int, str, datetime]]:
    """(place_id, device_id, observed_at) of the supporters' own crossings in the window."""
    lo = as_of - timedelta(hours=6)
    rows = session.execute(
        select(PlaceEvent.place_id, PlaceEvent.device_id, PlaceEvent.observed_at).where(
            PlaceEvent.device_id.in_(list(fix.supporters)),
            PlaceEvent.observed_at > lo,
            PlaceEvent.observed_at <= as_of,
        )
    ).all()
    return [(r.place_id, r.device_id, r.observed_at) for r in rows]


def _crossed_since(crossings, place_id: int, since: datetime | None) -> frozenset[str]:
    return frozenset(
        d for pid, d, at in crossings if pid == place_id and (since is None or at > since)
    )


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


def _write_event(
    session, group, place, fix, trackers, states, event_type, as_of, since=None, latest=None
):
    """Insert the one person row for this crossing, unless one already covers it.

    The row's time and lead are the first sighting on the new side and the
    tracker seen there (people/crossing.py), never the confirming sighting.
    `latest` caps the time: a place closed by an arrival elsewhere was left
    no later than that arrival (people/events_close.py).
    """
    target = "inside" if event_type == "ENTER" else "outside"
    lead, when = crossing(session, fix, place, target, since, as_of) or (fix.lead_device_id, as_of)
    if latest is not None and when > latest:
        when = latest
    if _existing_group_event(session, group.id, place.id, event_type, when, SETTLE_MINUTES):
        return None
    ids = _member_event_ids(session, fix, place.id, event_type, as_of)
    side = "inside" if event_type == "ENTER" else "outside"
    crossed = sum(1 for d in fix.supporters if states.get((d, place.id)) == side)
    row = GroupPlaceEvent(
        group_id=group.id,
        place_id=place.id,
        event_type=event_type,
        observed_at=when,
        member_event_ids=json.dumps(ids),
        members_crossed=crossed,
        members_considered=len(trackers) - len(fix.stale),
        members_stale=len(fix.stale),
        confidence="high" if fix.confidence == "likely" else "medium",
        notified_at=None,
        basis="person",
        note=event_note(group, place, fix, trackers, states, event_type),
        lead_device_id=lead,
    )
    return row if _insert_group_event(session, row) else None


def evaluate_person(session: Session, group, as_of: datetime) -> list[GroupPlaceEvent]:
    """Re-infer one person as of `as_of` and move every place's state."""
    fix, trackers, places = infer_person(session, group, as_of)
    states = _device_states(session, [t.device_id for t in trackers])
    crossings = _crossings(session, fix, as_of)
    now = datetime.now(UTC)
    inserted: list[GroupPlaceEvent] = []
    for place in places:
        row = session.get(PersonPlaceState, (group.id, place.id))
        if row is not None and row.since_observed_at and as_of < row.since_observed_at:
            continue  # backfill guard: a late older report never moves the state
        if row is None:
            row = PersonPlaceState(group_id=group.id, place_id=place.id, state="unknown")
            session.add(row)
        crossed = _crossed_since(crossings, place.id, row.last_transition_at)
        if row.state != "unknown" and expired(row.confirmed_at or row.since_observed_at, as_of):
            log.info("person_state_expired", group_id=group.id, place_id=place.id, state=row.state)
            row.state, row.pending_side, row.pending_since = "unknown", None, None
        target = person_target(fix, place, states, crossed, seeding=row.state == "unknown")
        if confirms(fix, place, states, crossed, row.state, target):
            row.confirmed_at = as_of
        since = row.last_transition_at
        s = step(row.state, row.pending_side, row.pending_since, since, target, as_of)
        row.state, row.pending_side, row.pending_since = s.state, s.pending_side, s.pending_since
        row.last_transition_at, row.since_observed_at, row.updated_at = (
            s.last_transition_at, as_of, now,
        )  # fmt: skip
        if s.event_type:
            event = _write_event(session, group, place, fix, trackers, states, s.event_type,
                                 as_of, since)  # fmt: skip
            if event is not None:
                inserted.append(event)
                log.debug("person_place_event", group_id=group.id, place_id=place.id,
                         event_type=s.event_type, confidence=fix.confidence)  # fmt: skip
    inserted.extend(_close_left(session, group, fix, trackers, places, states, inserted, as_of))
    session.flush()
    left_behind.evaluate(session, group, fix, trackers, places, as_of)
    return inserted


def _close_left(session, group, fix, trackers, places, states, inserted, as_of):
    """EXIT rows for places an arrival elsewhere proves the person left (uat116 #2)."""
    from findplus.people.events_close import close_left_places

    def write_exit(place, since, latest):
        return _write_event(session, group, place, fix, trackers, states, "EXIT", as_of,
                            since, latest)  # fmt: skip

    arrivals = [e for e in inserted if e.event_type == "ENTER"]
    return (
        close_left_places(session, group, places, arrivals, as_of, write_exit) if arrivals else []
    )


def run_person_hook(session: Session, observation: LocationObservation, settings: object = None):
    """The ingest hook: every person/pet this sighting's tracker belongs to."""
    fetched = observation.first_fetched_at
    if _quality.is_suspect(session, observation.id) or _quality.skewed(
        observation.observed_at, fetched
    ):
        return []
    as_of = _quality.as_of_for(observation.observed_at, fetched)
    inserted: list[GroupPlaceEvent] = []
    for group in person_groups_of(session, observation.device_id):
        inserted.extend(evaluate_person(session, group, as_of))
    return inserted

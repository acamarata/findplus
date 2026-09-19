"""DB-aware geofence hook.

Purpose : Evaluate every Place against one newly-inserted LocationObservation
          and persist the resulting PlaceState/PlaceEvent rows.
Inputs  : An open Session and the LocationObservation just added by ingest.py.
Outputs : list[GeofenceEvent] (no DB rows returned; ENTER/EXIT rows are
          written directly via the session).
Constraints: Never commits; the caller owns the transaction. GeofenceState and
          GeofenceEvent field names match their PlaceState/PlaceEvent ORM
          column names exactly, so `dataclasses.asdict` maps one to the other
          without a hand-written field-by-field copy.
Reuse: calls places.geofence.classify / advance.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from operator import attrgetter

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import LocationObservation, Place, PlaceEvent, PlaceState
from findplus.logging_setup import get_logger
from findplus.places.geofence import Fix, GeofenceEvent, GeofenceState, PlaceSpec, advance, classify

log = get_logger(__name__)

_spec_of = attrgetter(
    "id",
    "latitude_e7",
    "longitude_e7",
    "radius_meters",
    "enter_confirmations",
    "exit_confirmations",
)
_fix_of = attrgetter(
    "id",
    "device_id",
    "latitude_e7",
    "longitude_e7",
    "accuracy_meters",
    "observed_at",
    "last_fetched_at",
)


def _geo(row: PlaceState | None) -> GeofenceState:
    if row is None:
        return GeofenceState("unknown", None, 0, None, None)
    return GeofenceState(
        row.state, row.since_observed_at, row.streak, row.streak_side, row.last_observation_id
    )


def _save_state(session: Session, row: PlaceState | None, keys: dict, new: GeofenceState) -> None:
    if row is None:
        session.add(PlaceState(**keys, **asdict(new)))
        return
    for field, value in asdict(new).items():
        setattr(row, field, value)
    row.updated_at = keys["updated_at"]


def evaluate(
    session: Session,
    observation: LocationObservation,
    *,
    default_accuracy: float = 100.0,
) -> list[GeofenceEvent]:
    """Classify one new observation against every place, advance state, persist.

    `default_accuracy` is `Settings.geofence_default_accuracy_meters`, threaded
    in by ingest.py; a fix that reports no accuracy is treated as this many
    metres when the confidence band is chosen.
    """
    places = list(session.scalars(select(Place)).all())
    if not places:
        return []

    obs = observation
    fix = Fix(*_fix_of(obs))
    events: list[GeofenceEvent] = []
    now = datetime.now(UTC)

    for place in places:
        spec = PlaceSpec(*_spec_of(place))
        row = session.get(PlaceState, (place.id, obs.device_id))
        geo_state = _geo(row)
        cls = classify(spec, fix, default_accuracy)
        new_state, event = advance(geo_state, cls, fix, spec)
        state_keys = {"place_id": place.id, "device_id": obs.device_id, "updated_at": now}
        _save_state(session, row, state_keys, new_state)

        if event is not None:
            event_keys = {"place_id": place.id, "device_id": obs.device_id, "notified_at": None}
            session.add(PlaceEvent(**event_keys, **asdict(event)))
            events.append(event)
            log.info(
                "geofence_event",
                place_id=place.id,
                device_id=obs.device_id,
                event_type=event.event_type,
                confidence=event.confidence,
            )
        elif (
            geo_state.since_observed_at is not None
            and fix.observed_at <= geo_state.since_observed_at
        ):
            log.debug("geofence_backfill_ignored", place_id=place.id, device_id=obs.device_id)

    session.flush()
    return events

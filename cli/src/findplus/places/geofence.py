"""Pure geofence classification and hysteresis state machine.

Purpose : Classify one location fix against one circular place and advance a
          per-(place, device) state machine so ENTER/EXIT events fire only
          when a configured number of confirmations agree.
Inputs  : PlaceSpec (the geofence), Fix (one observed location), and the prior
          GeofenceState for that (place, device) pair.
Outputs : A Classification, and from advance()/evaluate_batch() an updated
          GeofenceState plus zero or more GeofenceEvent objects.
Constraints:
    - Pure: no DB access, no wall clock. Callers pass tz-aware `datetime`s;
      a naive one raises ValueError.
    - Crowdsourced fixes jitter by tens of metres and can arrive out of
      order; hysteresis (N consecutive same-side fixes) and an accuracy-scaled
      confidence band are what keep that jitter from flapping ENTER/EXIT
      (ADR-P1-04). A `low`-confidence fix never changes state.
    - `advance()` processes one fix; `evaluate_batch()` sorts by `observed_at`
      and folds `advance()` so an out-of-order batch still respects the
      backfill guard.
Reuse: findplus.geo.haversine_meters (distance only; no other geo logic here).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from findplus.geo import haversine_meters

Side = Literal["inside", "outside", "indeterminate"]
Confidence = Literal["high", "medium", "low"]
State = Literal["inside", "outside", "unknown"]


@dataclass(frozen=True)
class PlaceSpec:
    id: int
    latitude_e7: int
    longitude_e7: int
    radius_meters: int
    enter_confirmations: int
    exit_confirmations: int


@dataclass(frozen=True)
class Fix:
    observation_id: int
    device_id: str
    latitude_e7: int
    longitude_e7: int
    accuracy_meters: float | None
    observed_at: datetime
    fetched_at: datetime


@dataclass(frozen=True)
class Classification:
    side: Side
    confidence: Confidence
    distance_meters: float
    accuracy_meters: float


@dataclass(frozen=True)
class GeofenceState:
    state: State
    since_observed_at: datetime | None
    streak: int
    streak_side: str | None
    last_observation_id: int | None


@dataclass(frozen=True)
class GeofenceEvent:
    event_type: Literal["ENTER", "EXIT"]
    observation_id: int
    observed_at: datetime
    fetched_at: datetime
    confidence: str
    distance_meters: float
    accuracy_meters: float | None


def classify(place: PlaceSpec, fix: Fix, default_accuracy: float = 100.0) -> Classification:
    """Classify one fix as inside/outside/indeterminate of one place."""
    if fix.observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")

    lat1, lon1 = place.latitude_e7 / 1e7, place.longitude_e7 / 1e7
    lat2, lon2 = fix.latitude_e7 / 1e7, fix.longitude_e7 / 1e7
    distance = haversine_meters(lat1, lon1, lat2, lon2)

    acc = fix.accuracy_meters if fix.accuracy_meters is not None else default_accuracy

    if acc <= place.radius_meters / 2:
        confidence: Confidence = "high"
    elif acc <= place.radius_meters:
        confidence = "medium"
    else:
        confidence = "low"

    if confidence == "low":
        side: Side = "indeterminate"
    elif distance <= place.radius_meters:
        side = "inside"
    elif distance > place.radius_meters + max(acc, 50.0):
        side = "outside"
    else:
        side = "indeterminate"

    return Classification(
        side=side, confidence=confidence, distance_meters=distance, accuracy_meters=acc
    )


def classify_point(
    place: PlaceSpec,
    latitude: float,
    longitude: float,
    accuracy_meters: float | None,
    default_accuracy: float = 100.0,
) -> Classification:
    """classify() for a read-only lookup with no observation_id/device_id in hand.

    Used by the timeline API (U30b) to label an already-stored point with the
    saved place it falls inside, without touching the hysteresis state machine
    (that stays the sole owner of ENTER/EXIT truth in advance()). `observed_at`
    only needs to be tz-aware for classify()'s guard, not any real timestamp,
    since side/confidence never depend on it.
    """
    fix = Fix(
        observation_id=0,
        device_id="",
        latitude_e7=round(latitude * 1e7),
        longitude_e7=round(longitude * 1e7),
        accuracy_meters=accuracy_meters,
        observed_at=datetime.now(UTC),
        fetched_at=datetime.now(UTC),
    )
    return classify(place, fix, default_accuracy)


def _crossing(
    event_type: Literal["ENTER", "EXIT"], cls: Classification, fix: Fix
) -> tuple[GeofenceState, GeofenceEvent]:
    """Build the post-crossing state (streak reset) and its event."""
    new_state = GeofenceState(
        state="inside" if event_type == "ENTER" else "outside",
        since_observed_at=fix.observed_at,
        streak=0,
        streak_side=None,
        last_observation_id=fix.observation_id,
    )
    event = GeofenceEvent(
        event_type=event_type,
        observation_id=fix.observation_id,
        observed_at=fix.observed_at,
        fetched_at=fix.fetched_at,
        confidence=cls.confidence,
        distance_meters=cls.distance_meters,
        # The fix's OWN accuracy, never cls.accuracy_meters: classify() has
        # already substituted `default_accuracy` there, so copying it would
        # persist "no accuracy reported" as a measured 100 m reading.
        accuracy_meters=fix.accuracy_meters,
    )
    return new_state, event


def advance(
    state: GeofenceState, cls: Classification, fix: Fix, place: PlaceSpec
) -> tuple[GeofenceState, GeofenceEvent | None]:
    """Advance the hysteresis state machine by one classified fix."""
    if cls.side == "indeterminate":
        return state, None

    if state.since_observed_at is not None and fix.observed_at <= state.since_observed_at:
        # Backfill: an older fix arriving after a newer one already moved state.
        return state, None

    streak = state.streak + 1 if cls.side == state.streak_side else 1
    streak_side = cls.side

    if state.state == "unknown":
        new_state = GeofenceState(
            state=cls.side,
            since_observed_at=fix.observed_at,
            streak=streak,
            streak_side=streak_side,
            last_observation_id=fix.observation_id,
        )
        return new_state, None

    if state.state == "outside" and cls.side == "inside" and streak >= place.enter_confirmations:
        return _crossing("ENTER", cls, fix)

    if state.state == "inside" and cls.side == "outside" and streak >= place.exit_confirmations:
        return _crossing("EXIT", cls, fix)

    new_state = GeofenceState(
        state=state.state,
        since_observed_at=state.since_observed_at,
        streak=streak,
        streak_side=streak_side,
        last_observation_id=fix.observation_id,
    )
    return new_state, None


def evaluate_batch(
    state: GeofenceState,
    fixes: list[Fix],
    place: PlaceSpec,
    default_accuracy: float = 100.0,
) -> tuple[GeofenceState, list[GeofenceEvent]]:
    """Fold advance() over a batch of fixes, processed in observed_at order."""
    events: list[GeofenceEvent] = []
    for fix in sorted(fixes, key=lambda f: f.observed_at):
        cls = classify(place, fix, default_accuracy)
        state, event = advance(state, cls, fix, place)
        if event is not None:
            events.append(event)
    return state, events

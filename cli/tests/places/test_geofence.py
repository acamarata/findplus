"""places/geofence.py: classify, advance, evaluate_batch.

Fixture points sit due north/south of the place centre (same longitude), so
haversine distance is exactly `EARTH_RADIUS_METERS * delta_latitude_radians`
for the small offsets used here — no hand-tuned "111,320 m/degree" numbers.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from findplus.geo import EARTH_RADIUS_METERS
from findplus.places.geofence import (
    Classification,
    Fix,
    GeofenceState,
    PlaceSpec,
    advance,
    classify,
    evaluate_batch,
)

CENTER_LAT_E7 = 411000000
CENTER_LON_E7 = -806400000
T0 = datetime(2026, 9, 19, 10, 0, 0, tzinfo=UTC)


def _place(radius=100, enter=1, exit_=2) -> PlaceSpec:
    return PlaceSpec(
        id=1,
        latitude_e7=CENTER_LAT_E7,
        longitude_e7=CENTER_LON_E7,
        radius_meters=radius,
        enter_confirmations=enter,
        exit_confirmations=exit_,
    )


def _fix(meters_north: float, acc: float | None, when: datetime, obs_id: int = 1) -> Fix:
    delta_rad = meters_north / EARTH_RADIUS_METERS
    lat_e7 = CENTER_LAT_E7 + round(math.degrees(delta_rad) * 1e7)
    return Fix(
        observation_id=obs_id,
        device_id="dev1",
        latitude_e7=lat_e7,
        longitude_e7=CENTER_LON_E7,
        accuracy_meters=acc,
        observed_at=when,
        fetched_at=when,
    )


def _unknown_state() -> GeofenceState:
    return GeofenceState(
        state="unknown",
        since_observed_at=None,
        streak=0,
        streak_side=None,
        last_observation_id=None,
    )


def _outside_state(since: datetime | None = None) -> GeofenceState:
    return GeofenceState(
        state="outside",
        since_observed_at=since,
        streak=0,
        streak_side=None,
        last_observation_id=None,
    )


def _inside_state(since: datetime | None = None) -> GeofenceState:
    return GeofenceState(
        state="inside",
        since_observed_at=since,
        streak=0,
        streak_side=None,
        last_observation_id=None,
    )


# --------------------------------------------------------------- classify()
def test_classify_inside_high_confidence() -> None:
    cls = classify(_place(), _fix(80, 30.0, T0))
    assert cls.side == "inside"
    assert cls.confidence == "high"
    assert cls.distance_meters == pytest.approx(80, abs=0.1)


def test_classify_outside_high_confidence() -> None:
    cls = classify(_place(), _fix(151, 30.0, T0))
    assert cls.side == "outside"
    assert cls.confidence == "high"


@pytest.mark.parametrize("meters", [101, 130, 149])
def test_classify_band_is_indeterminate(meters: float) -> None:
    # radius 100, acc 30 -> outside needs d > radius + max(acc, 50) = 150
    cls = classify(_place(), _fix(meters, 30.0, T0))
    assert cls.side == "indeterminate"


def test_classify_band_edge_151_is_outside() -> None:
    cls = classify(_place(), _fix(151, 30.0, T0))
    assert cls.side == "outside"


def test_classify_low_accuracy_is_indeterminate() -> None:
    cls = classify(_place(), _fix(50, 500.0, T0))
    assert cls.confidence == "low"
    assert cls.side == "indeterminate"


def test_classify_none_accuracy_uses_default_medium() -> None:
    cls = classify(_place(), _fix(50, None, T0), default_accuracy=100.0)
    assert cls.confidence == "medium"


@pytest.mark.parametrize(
    "acc,expected",
    [(50.0, "high"), (51.0, "medium"), (100.0, "medium"), (101.0, "low")],
)
def test_classify_confidence_boundaries(acc: float, expected: str) -> None:
    cls = classify(_place(radius=100), _fix(10, acc, T0))
    assert cls.confidence == expected


def test_classify_naive_datetime_raises() -> None:
    naive_fix = Fix(
        observation_id=1,
        device_id="dev1",
        latitude_e7=CENTER_LAT_E7,
        longitude_e7=CENTER_LON_E7,
        accuracy_meters=30.0,
        observed_at=datetime(2026, 9, 19, 10, 0, 0),
        fetched_at=T0,
    )
    with pytest.raises(ValueError):
        classify(_place(), naive_fix)


def test_confidence_never_low_while_side_not_indeterminate() -> None:
    for meters in (10, 80, 130, 151, 300):
        cls = classify(_place(), _fix(meters, 30.0, T0))
        if cls.confidence == "low":
            assert cls.side == "indeterminate"


# ------------------------------------------------------------------- seed
def test_seed_from_unknown_inside_sets_state_no_event() -> None:
    place = _place()
    fix = _fix(50, 30.0, T0)
    state, event = advance(_unknown_state(), classify(place, fix), fix, place)
    assert state.state == "inside"
    assert state.since_observed_at == T0
    assert event is None


def test_seed_from_unknown_outside_sets_state_no_event() -> None:
    fix = _fix(200, 30.0, T0)
    state, event = advance(_unknown_state(), classify(_place(), fix), fix, _place())
    assert state.state == "outside"
    assert event is None


def test_indeterminate_fix_never_changes_unknown_state() -> None:
    fix = _fix(500, 500.0, T0)  # low accuracy -> indeterminate
    state, event = advance(_unknown_state(), classify(_place(), fix), fix, _place())
    assert state.state == "unknown"
    assert state.streak == 0
    assert event is None


# ------------------------------------------------------------------- enter
@pytest.mark.parametrize("confirmations", [1, 2, 3, 5])
def test_enter_after_n_confirmations(confirmations: int) -> None:
    place = _place(enter=confirmations)
    state = _outside_state()
    events = []
    for i in range(confirmations):
        fix = _fix(50, 30.0, T0 + timedelta(minutes=i), obs_id=i)
        state, event = advance(state, classify(place, fix), fix, place)
        events.append(event)
    assert events[:-1] == [None] * (confirmations - 1)
    assert events[-1] is not None
    assert events[-1].event_type == "ENTER"
    assert state.state == "inside"


def test_enter_confirmations_3_two_fixes_no_event_third_fires() -> None:
    place = _place(enter=3)
    state = _outside_state()
    for i in range(2):
        fix = _fix(50, 30.0, T0 + timedelta(minutes=i), obs_id=i)
        state, event = advance(state, classify(place, fix), fix, place)
        assert event is None
    fix = _fix(50, 30.0, T0 + timedelta(minutes=2), obs_id=2)
    state, event = advance(state, classify(place, fix), fix, place)
    assert event is not None and event.event_type == "ENTER"


# -------------------------------------------------------------------- exit
def test_exit_requires_two_confirmations_by_default() -> None:
    place = _place()
    state = _inside_state(since=T0 - timedelta(hours=1))
    fix1 = _fix(200, 30.0, T0, obs_id=1)
    state, event1 = advance(state, classify(place, fix1), fix1, place)
    assert event1 is None
    assert state.state == "inside"
    fix2 = _fix(200, 30.0, T0 + timedelta(minutes=1), obs_id=2)
    state, event2 = advance(state, classify(place, fix2), fix2, place)
    assert event2 is not None
    assert event2.event_type == "EXIT"
    assert state.state == "outside"


def test_single_outside_fix_then_inside_produces_no_exit() -> None:
    place = _place()
    state = _inside_state(since=T0 - timedelta(hours=1))
    fix1 = _fix(200, 30.0, T0, obs_id=1)
    state, event1 = advance(state, classify(place, fix1), fix1, place)
    assert event1 is None
    fix2 = _fix(50, 30.0, T0 + timedelta(minutes=1), obs_id=2)
    state, event2 = advance(state, classify(place, fix2), fix2, place)
    assert event2 is None
    assert state.state == "inside"


# --------------------------------------------------------------- backfill
def test_backfill_does_not_change_state_or_streak() -> None:
    place = _place()
    seed_fix = _fix(50, 30.0, T0, obs_id=1)
    state, _event = advance(_unknown_state(), classify(place, seed_fix), seed_fix, place)
    assert state.since_observed_at == T0
    assert state.streak == 1

    backfill_fix = _fix(50, 30.0, T0 - timedelta(minutes=10), obs_id=2)
    new_state, new_event = advance(state, classify(place, backfill_fix), backfill_fix, place)
    assert new_state == state
    assert new_event is None


# ----------------------------------------------------------------- jitter
def test_jitter_fixture_one_enter_zero_exit() -> None:
    """40 alternating fixes (PROMPT.md §4a): the outside side must actually
    classify as outside, not fall into the indeterminate band -- with
    radius=100 and acc=30, outside requires d > radius + max(acc, 50) = 150,
    so the outside leg alternates at 200 m (120 m only ever landed as
    indeterminate and never exercised the exit-hysteresis branch at all).
    """
    place = _place()
    fixes = []
    for i in range(40):
        meters = 80 if i % 2 == 0 else 200
        fixes.append(_fix(meters, 30.0, T0 + timedelta(minutes=i), obs_id=i))
    state, events = evaluate_batch(_outside_state(since=T0 - timedelta(hours=1)), fixes, place)
    enters = [e for e in events if e.event_type == "ENTER"]
    exits = [e for e in events if e.event_type == "EXIT"]
    assert len(enters) == 1
    assert len(exits) == 0
    assert state.state == "inside"


def test_evaluate_batch_sorts_out_of_order_input() -> None:
    place = _place()
    in_order = [_fix(50, 30.0, T0 + timedelta(minutes=i), obs_id=i) for i in range(5)]
    out_of_order = list(reversed(in_order))

    state_a, events_a = evaluate_batch(_outside_state(), in_order, place)
    state_b, events_b = evaluate_batch(_outside_state(), out_of_order, place)

    assert state_a == state_b
    assert [(e.event_type, e.observation_id) for e in events_a] == [
        (e.event_type, e.observation_id) for e in events_b
    ]


def test_evaluate_batch_empty_fixes_returns_unchanged_state() -> None:
    place = _place()
    state = _outside_state()
    new_state, events = evaluate_batch(state, [], place)
    assert new_state == state
    assert events == []


def test_classification_dataclass_is_frozen() -> None:
    cls = classify(_place(), _fix(50, 30.0, T0))
    assert isinstance(cls, Classification)
    with pytest.raises(AttributeError):
        cls.side = "outside"  # type: ignore[misc]

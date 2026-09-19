"""Integration: places/events.py wired into ingest_observations after flush."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from findplus.findhub.types import RawObservation
from sqlalchemy import select

from findplus.db.models import LocationObservation, Place, PlaceEvent, PlaceState
from findplus.ingest import ingest_observations

T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def make_obs(lat_e7: int, lon_e7: int, observed_at: datetime, acc: float = 30.0) -> RawObservation:
    return RawObservation(
        device_id="dev1",
        device_name="Tag1",
        latitude_e7=lat_e7,
        longitude_e7=lon_e7,
        observed_at=observed_at,
        accuracy_meters=acc,
        source="crowdsourced",
        is_own_report=False,
    )


@pytest.fixture(autouse=True)
def _seed(session):
    from findplus.db.models import Device

    session.add(
        Device(
            device_id="dev1",
            name="Tag1",
            is_tracked=False,
            first_seen_at=T0,
            last_seen_at=T0,
        )
    )
    session.add(
        Place(
            name="Home",
            latitude_e7=411000000,
            longitude_e7=-806400000,
            radius_meters=100,
            color="#2f80ed",
            enter_confirmations=1,
            exit_confirmations=2,
            created_at=T0,
            updated_at=T0,
        )
    )
    session.flush()


def test_no_places_no_events(session):
    session.query(Place).delete()
    session.flush()
    ingest_observations(session, [make_obs(411000000, -806400000, T0)])
    assert session.scalar(select(PlaceEvent).limit(1)) is None


def test_first_fix_seeds_state_inside(session):
    # ~90m north of centre, inside the 100m radius.
    ingest_observations(session, [make_obs(411000900, -806400000, T0)])
    place = session.scalar(select(Place))
    state = session.get(PlaceState, (place.id, "dev1"))
    assert state.state == "inside"
    assert session.scalar(select(PlaceEvent).limit(1)) is None


def test_enter_event_fired(session):
    place = session.scalar(select(Place))
    session.add(
        PlaceState(
            place_id=place.id,
            device_id="dev1",
            state="outside",
            streak=0,
            streak_side=None,
            since_observed_at=None,
            last_observation_id=None,
            updated_at=T0,
        )
    )
    session.flush()
    ingest_observations(session, [make_obs(411000900, -806400000, T0)])
    events = list(session.scalars(select(PlaceEvent)))
    assert len(events) == 1
    assert events[0].event_type == "ENTER"
    assert events[0].confidence in {"high", "medium", "low"}
    assert events[0].observation_id is not None


def test_repeat_inside_no_new_event(session):
    place = session.scalar(select(Place))
    session.add(
        PlaceState(
            place_id=place.id,
            device_id="dev1",
            state="outside",
            streak=0,
            streak_side=None,
            since_observed_at=None,
            last_observation_id=None,
            updated_at=T0,
        )
    )
    session.flush()
    ingest_observations(session, [make_obs(411000900, -806400000, T0)])
    ingest_observations(session, [make_obs(411000900, -806400000, T0 + timedelta(minutes=5))])
    events = list(session.scalars(select(PlaceEvent)))
    assert len(events) == 1


def test_out_of_order_batch(session):
    place = session.scalar(select(Place))
    session.add(
        PlaceState(
            place_id=place.id,
            device_id="dev1",
            state="outside",
            streak=0,
            streak_side=None,
            since_observed_at=None,
            last_observation_id=None,
            updated_at=T0,
        )
    )
    session.flush()
    # 170m north (outside) at t0+60s listed FIRST; 90m north (inside) at t0 listed SECOND.
    # The sort processes t0/90m first.
    obs_later_outside = make_obs(411001700, -806400000, T0 + timedelta(seconds=60))
    obs_first_inside = make_obs(411000900, -806400000, T0)
    ingest_observations(session, [obs_later_outside, obs_first_inside])

    state = session.get(PlaceState, (place.id, "dev1"))
    events = list(session.scalars(select(PlaceEvent)))
    assert state.state == "inside"
    assert len(events) == 1
    assert events[0].event_type == "ENTER"


def test_observation_id_matches(session):
    place = session.scalar(select(Place))
    session.add(
        PlaceState(
            place_id=place.id,
            device_id="dev1",
            state="outside",
            streak=0,
            streak_side=None,
            since_observed_at=None,
            last_observation_id=None,
            updated_at=T0,
        )
    )
    session.flush()
    ingest_observations(session, [make_obs(411000900, -806400000, T0)])
    event = session.scalar(select(PlaceEvent))
    obs = session.scalar(select(LocationObservation))
    assert event.observation_id == obs.id


def test_duplicate_observation_does_not_trigger_evaluate(session):
    """Ad-hoc QA-B case: ingesting the same fix twice fires evaluate only once."""
    place = session.scalar(select(Place))
    session.add(
        PlaceState(
            place_id=place.id,
            device_id="dev1",
            state="outside",
            streak=0,
            streak_side=None,
            since_observed_at=None,
            last_observation_id=None,
            updated_at=T0,
        )
    )
    session.flush()
    obs = make_obs(411000900, -806400000, T0)
    ingest_observations(session, [obs])
    count_after_first = len(list(session.scalars(select(PlaceEvent))))
    ingest_observations(session, [make_obs(411000900, -806400000, T0)])
    count_after_second = len(list(session.scalars(select(PlaceEvent))))
    assert count_after_second == count_after_first


def test_hook_failure_never_loses_the_batch(session, monkeypatch) -> None:
    """A raising post-ingest hook must not discard the observations it ran on.

    The provider will not hand the same fixes back, so a bug in the geofence
    (or, later, the groups/alerts) hook has to be logged and stepped over, not
    allowed to roll back the batch.
    """

    def boom(_session, _lo):
        raise RuntimeError("hook exploded")

    monkeypatch.setattr("findplus.ingest._geofence_evaluate", boom)
    result = ingest_observations(session, [make_obs(411000900, -806400000, T0)])
    assert result.inserted == 1
    session.flush()
    assert len(list(session.scalars(select(LocationObservation)))) == 1


def test_event_accuracy_is_null_when_the_fix_reported_none(session):
    """A fix with no accuracy must not be stored as a measured 100 m reading.

    classify() substitutes `default_accuracy` to pick a confidence band; that
    substitution is a judgement, not an observation, so it must never reach
    `place_events.accuracy_meters` (PROMPT.md §2 invariant 12: never fabricate).
    """
    place = session.scalar(select(Place))
    session.add(
        PlaceState(
            place_id=place.id,
            device_id="dev1",
            state="outside",
            since_observed_at=T0 - timedelta(hours=2),
            streak=0,
            streak_side=None,
            last_observation_id=None,
            updated_at=T0,
        )
    )
    session.flush()
    # Radius 100 m, so accuracy=None -> default 100.0 -> "medium", not "low".
    ingest_observations(session, [make_obs(411000000, -806400000, T0, acc=None)])
    event = session.scalar(select(PlaceEvent))
    assert event is not None
    assert event.event_type == "ENTER"
    assert event.confidence == "medium"
    assert event.accuracy_meters is None


def test_settings_default_accuracy_is_threaded_into_classify(session):
    """geofence_default_accuracy_meters (data-model.md § Settings) is honoured.

    With a default of 200 m against a 100 m radius the fix is low-confidence,
    so it is indeterminate and must leave the state machine untouched.
    """
    import types

    settings = types.SimpleNamespace(
        geofence_default_accuracy_meters=200.0,
        group_window_minutes=30,
        presence_window_minutes=60,
    )
    ingest_observations(session, [make_obs(411000000, -806400000, T0, acc=None)], settings=settings)
    place = session.scalar(select(Place))
    state = session.get(PlaceState, (place.id, "dev1"))
    assert state.state == "unknown"
    assert session.scalar(select(PlaceEvent).limit(1)) is None

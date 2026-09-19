"""places/repo.py: list, create, update, delete, events, presence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from findplus.db.models import Device, LocationObservation, PlaceEvent, PlaceState
from findplus.places.repo import (
    create_place,
    current_presence,
    delete_place,
    list_place_events,
    list_places,
    update_place,
)


@pytest.fixture(autouse=True)
def _devices(session):
    session.add(
        Device(
            device_id="dev1",
            name="Tag1",
            is_tracked=False,
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
    )
    session.add(
        Device(
            device_id="dev2",
            name="Tag2",
            is_tracked=False,
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
    )
    session.flush()


def _make_observation(session, device_id: str = "dev1", when: datetime | None = None) -> int:
    when = when or datetime.now(UTC)
    obs = LocationObservation(
        device_id=device_id,
        device_name="Tag",
        latitude_e7=0,
        longitude_e7=0,
        observed_at=when,
        first_fetched_at=when,
        last_fetched_at=when,
        times_returned=1,
    )
    session.add(obs)
    session.flush()
    return obs.id


def test_create_and_list_empty(session):
    assert list_places(session) == []
    place = create_place(
        session, name="Home", latitude_e7=411000000, longitude_e7=-806400000, radius_meters=100
    )
    assert place.id is not None


def test_list_after_create(session):
    create_place(
        session, name="Home", latitude_e7=411000000, longitude_e7=-806400000, radius_meters=100
    )
    rows = list_places(session)
    assert len(rows) == 1
    assert rows[0].name == "Home"
    assert rows[0]._devices_inside == []


def test_create_duplicate_name(session):
    create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    with pytest.raises(ValueError, match="already exists"):
        create_place(session, name="Home", latitude_e7=1, longitude_e7=1, radius_meters=100)


def test_create_radius_min(session):
    with pytest.raises(ValueError, match="radius_meters"):
        create_place(session, name="P", latitude_e7=0, longitude_e7=0, radius_meters=19)


def test_create_radius_max(session):
    with pytest.raises(ValueError, match="radius_meters"):
        create_place(session, name="P", latitude_e7=0, longitude_e7=0, radius_meters=5001)


def test_update_name(session):
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    update_place(session, place.id, name="NewName")
    assert list_places(session)[0].name == "NewName"


def test_update_not_found(session):
    with pytest.raises(ValueError, match="not found"):
        update_place(session, 9999, name="X")


def test_delete_cascade(session):
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    obs_id = _make_observation(session)
    session.add(
        PlaceState(
            place_id=place.id,
            device_id="dev1",
            state="inside",
            streak=0,
            since_observed_at=None,
            last_observation_id=None,
            updated_at=datetime.now(UTC),
        )
    )
    session.add(
        PlaceEvent(
            place_id=place.id,
            device_id="dev1",
            event_type="ENTER",
            observed_at=datetime.now(UTC),
            fetched_at=datetime.now(UTC),
            observation_id=obs_id,
            confidence="high",
            distance_meters=1.0,
        )
    )
    session.flush()
    place_id = place.id
    delete_place(session, place_id)
    assert session.get(PlaceState, (place_id, "dev1")) is None
    assert session.scalar(select(func.count()).where(PlaceEvent.place_id == place_id)) == 0


def test_list_place_events_filter(session):
    p1 = create_place(session, name="P1", latitude_e7=0, longitude_e7=0, radius_meters=100)
    p2 = create_place(session, name="P2", latitude_e7=1, longitude_e7=1, radius_meters=100)
    # Distinct timestamps: Windows clock resolution would otherwise collide on
    # the (device_id, observed_at, lat, lon) unique key.
    base = datetime.now(UTC) - timedelta(minutes=2)
    obs1_id = _make_observation(session, when=base)
    obs2_id = _make_observation(session, when=base + timedelta(minutes=1))
    session.add(
        PlaceEvent(
            place_id=p1.id,
            device_id="dev1",
            event_type="ENTER",
            observed_at=datetime.now(UTC),
            fetched_at=datetime.now(UTC),
            observation_id=obs1_id,
            confidence="high",
            distance_meters=1.0,
        )
    )
    session.add(
        PlaceEvent(
            place_id=p2.id,
            device_id="dev1",
            event_type="ENTER",
            observed_at=datetime.now(UTC),
            fetched_at=datetime.now(UTC),
            observation_id=obs2_id,
            confidence="high",
            distance_meters=1.0,
        )
    )
    session.flush()
    rows = list_place_events(session, place_id=p1.id)
    assert len(rows) == 1
    assert rows[0]._place_name == "P1"


def test_devices_inside(session):
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    state = PlaceState(
        place_id=place.id,
        device_id="dev1",
        state="inside",
        streak=0,
        since_observed_at=None,
        last_observation_id=None,
        updated_at=datetime.now(UTC),
    )
    session.add(state)
    session.flush()
    assert list_places(session)[0]._devices_inside == ["dev1"]
    state.state = "outside"
    session.flush()
    assert list_places(session)[0]._devices_inside == []


def test_list_place_events_limit_ordered(session):
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    for i in range(5):
        when = datetime(2026, 9, 19, 10, i, tzinfo=UTC)
        obs_id = _make_observation(session, when=when)
        session.add(
            PlaceEvent(
                place_id=place.id,
                device_id="dev1",
                event_type="ENTER",
                observed_at=when,
                fetched_at=when,
                observation_id=obs_id,
                confidence="high",
                distance_meters=1.0,
            )
        )
    session.flush()
    rows = list_place_events(session, limit=3)
    assert len(rows) == 3
    assert rows[0].observed_at > rows[-1].observed_at


def test_current_presence_empty(session):
    assert current_presence(session) == []


def _place_state(session, place_id, *, streak, side, state="inside"):
    now = datetime.now(UTC)
    session.add(
        PlaceState(
            place_id=place_id,
            device_id="dev1",
            state=state,
            since_observed_at=now,
            streak=streak,
            streak_side=side,
            last_observation_id=None,
            updated_at=now,
        )
    )
    session.flush()


def test_moving_a_place_clears_the_confirmation_streaks(session):
    """A streak counted against the old circle must not confirm a crossing of the new one.

    Without this, moving a place across town lets the very next fix satisfy
    `exit_confirmations` and emit an EXIT anchored to geometry that no longer
    exists at that location.
    """
    place = create_place(
        session, name="Home", latitude_e7=411000000, longitude_e7=-806400000, radius_meters=100
    )
    _place_state(session, place.id, streak=1, side="outside")
    update_place(session, place.id, latitude_e7=511000000)
    row = session.get(PlaceState, (place.id, "dev1"))
    assert row.streak == 0
    assert row.streak_side is None
    # The state itself is kept: it is re-derived once fixes agree on the new circle.
    assert row.state == "inside"


def test_resizing_a_place_clears_the_streaks(session):
    place = create_place(
        session, name="Home", latitude_e7=411000000, longitude_e7=-806400000, radius_meters=100
    )
    _place_state(session, place.id, streak=2, side="inside")
    update_place(session, place.id, radius_meters=400)
    assert session.get(PlaceState, (place.id, "dev1")).streak == 0


def test_cosmetic_update_keeps_the_streak(session):
    """Renaming or recolouring a place changes no geometry, so hysteresis survives."""
    place = create_place(
        session, name="Home", latitude_e7=411000000, longitude_e7=-806400000, radius_meters=100
    )
    _place_state(session, place.id, streak=2, side="inside")
    update_place(session, place.id, name="House", color="#123456", radius_meters=100)
    row = session.get(PlaceState, (place.id, "dev1"))
    assert row.streak == 2
    assert row.streak_side == "inside"

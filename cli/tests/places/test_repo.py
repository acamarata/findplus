"""places/repo.py: create, list, update, delete and the confirmation streaks.

The place-event listing and presence tests live in test_repo_events.py (split
under PRI rule 7). Shared seed helpers live in _helpers.py, the device fixture
in conftest.py."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from findplus.db.models import PlaceEvent, PlaceState
from findplus.places.repo import (
    create_place,
    delete_place,
    list_places,
    update_place,
)

from ._helpers import _devices  # noqa: F401  (autouse where imported)
from ._helpers import make_observation as _make_observation


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

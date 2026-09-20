"""groups/repo.py — the DB-to-engine wiring behind presence and the event log."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from findplus.db.models import (
    Device,
    DeviceGroup,
    Group,
    GroupPlaceEvent,
    LocationObservation,
    Place,
    PlaceState,
)
from findplus.groups.repo import (
    build_presence,
    create_group,
    list_group_place_events,
    update_group,
)

NOW = datetime.now(UTC)


def _place(session, name: str, radius: int) -> Place:
    place = Place(
        name=name,
        latitude_e7=411000000,
        longitude_e7=-806400000,
        radius_meters=radius,
        color="#2f80ed",
        enter_confirmations=1,
        exit_confirmations=2,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(place)
    session.flush()
    return place


@pytest.fixture
def group(session) -> Group:
    group = Group(
        name="family",
        color="#27ae60",
        quorum="majority",
        cluster_radius_meters=150,
        stale_after_minutes=90,
        created_at=NOW,
    )
    session.add(group)
    session.add(Device(device_id="dev1", name="Tag1", first_seen_at=NOW, last_seen_at=NOW))
    session.flush()
    session.add(DeviceGroup(device_id="dev1", group_id=group.id))
    session.add(
        LocationObservation(
            device_id="dev1",
            device_name="Tag1",
            latitude_e7=411000000,
            longitude_e7=-806400000,
            observed_at=NOW - timedelta(minutes=2),
            first_fetched_at=NOW,
            last_fetched_at=NOW,
        )
    )
    session.flush()
    return group


def test_overlapping_places_report_the_most_specific_one(session, group) -> None:
    """member_status reads inside_places[0], so the order must be deterministic.

    A tag standing inside both "Home" (50 m) and a wide "Neighbourhood" (1 km)
    is at Home; an unordered query would name either one, differently per call.
    """
    wide = _place(session, "Neighbourhood", 1000)
    home = _place(session, "Home", 50)
    for place in (wide, home):
        session.add(
            PlaceState(
                place_id=place.id,
                device_id="dev1",
                state="inside",
                since_observed_at=NOW - timedelta(hours=1),
                streak=1,
                streak_side="inside",
                last_observation_id=None,
                updated_at=NOW,
            )
        )
    session.flush()

    _, statuses = build_presence(session, group, window_minutes=60, movement_threshold_meters=25)
    assert [s.place for s in statuses] == ["Home"]


def test_group_event_log_carries_the_note(session, group) -> None:
    """api-contract.md § routes_groups.py pins `note` on GET /api/groups/events."""
    place = _place(session, "Home", 100)
    session.add(
        GroupPlaceEvent(
            group_id=group.id,
            place_id=place.id,
            event_type="EXIT",
            observed_at=NOW,
            member_event_ids="[]",
            members_crossed=1,
            members_considered=3,
            members_stale=2,
            confidence="low",
            notified_at=None,
        )
    )
    session.flush()

    rows = list_group_place_events(session, group_id=group.id)
    assert rows[0]["note"] == "1 of 3 tags left Home; 2 tags have no recent fix."


# ------------------------------------------------------------------- icons (P2-E2)
def test_create_group_default_icon(session) -> None:
    assert create_group(session, name="Family").icon == "lucide:users"


def test_create_group_custom_icon(session) -> None:
    assert create_group(session, name="Family", icon="lucide:dog").icon == "lucide:dog"


def test_create_group_invalid_icon_raises(session) -> None:
    with pytest.raises(ValueError, match="icon must match lucide:"):
        create_group(session, name="Family", icon="bogus")


def test_update_group_icon(session) -> None:
    group = create_group(session, name="Family")
    update_group(session, group.id, icon="lucide:cat")
    assert session.get(Group, group.id).icon == "lucide:cat"


def test_update_group_invalid_icon_leaves_the_row_alone(session) -> None:
    """Validation runs before any setattr, so a bad PUT cannot half-apply."""
    group = create_group(session, name="Family", icon="lucide:dog")
    with pytest.raises(ValueError, match="one of the available lucide icon ids"):
        update_group(session, group.id, name="Renamed", icon="lucide:not-real")
    refetched = session.get(Group, group.id)
    assert refetched.icon == "lucide:dog"
    assert refetched.name == "Family"

"""cli/src/findplus/groups/events.py -- group quorum firing at ingest time.

Covers the E6 CR-C finding: nothing populated group_place_events, so group
alert rules could never fire. Exercises evaluate_group_events() directly
(unit-level, deterministic `now`) and the ingest.py wiring (integration:
the hook never loses the observation batch when it raises).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from findplus.db.models import (
    Device,
    DeviceGroup,
    Group,
    GroupPlaceEvent,
    LocationObservation,
    Place,
    PlaceEvent,
    PlaceState,
)
from findplus.groups.events import evaluate_group_events
from findplus.ingest import ingest_observations

T0 = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)


class _Settings:
    group_window_minutes = 30
    presence_window_minutes = 60


def _seed_group(session, quorum: str = "majority") -> tuple[Group, Place]:
    place = Place(
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
    group = Group(
        name="family",
        color="#27ae60",
        quorum=quorum,
        cluster_radius_meters=150,
        stale_after_minutes=90,
        created_at=T0,
    )
    session.add_all([place, group])
    session.flush()
    for device_id in ("a", "b", "c"):
        session.add(
            Device(
                device_id=device_id,
                name=device_id,
                is_tracked=True,
                first_seen_at=T0,
                last_seen_at=T0,
            )
        )
    session.flush()
    for device_id in ("a", "b", "c"):
        session.add(DeviceGroup(device_id=device_id, group_id=group.id))
    session.flush()
    return group, place


def _add_fix(session, device_id: str, observed_at: datetime) -> LocationObservation:
    """A recent LocationObservation, so the member is not stale at `observed_at`."""
    lo = LocationObservation(
        device_id=device_id,
        device_name=device_id,
        latitude_e7=411000000,
        longitude_e7=-806400000,
        observed_at=observed_at,
        first_fetched_at=observed_at,
        last_fetched_at=observed_at,
        times_returned=1,
        source="crowdsourced",
        is_own_report=False,
    )
    session.add(lo)
    session.flush()
    return lo


def _add_place_event(
    session, place: Place, device_id: str, event_type: str, observed_at: datetime
) -> PlaceEvent:
    lo = _add_fix(session, device_id, observed_at)
    pe = PlaceEvent(
        place_id=place.id,
        device_id=device_id,
        event_type=event_type,
        observed_at=observed_at,
        fetched_at=observed_at,
        observation_id=lo.id,
        confidence="high",
        distance_meters=10.0,
        accuracy_meters=10.0,
        notified_at=None,
    )
    session.add(pe)
    session.flush()
    return pe


def test_majority_fires_on_2_of_3(session):
    _group, place = _seed_group(session)
    pe_a = _add_place_event(session, place, "a", "ENTER", T0)
    _add_place_event(session, place, "b", "ENTER", T0 + timedelta(minutes=1))
    _add_fix(session, "c", T0)  # reporting, but never crossed

    rows = evaluate_group_events(session, pe_a, _Settings(), now=T0 + timedelta(minutes=1))

    assert len(rows) == 1
    assert rows[0].members_crossed == 2
    assert rows[0].members_considered == 3
    assert rows[0].event_type == "ENTER"
    saved = session.scalar(select(GroupPlaceEvent))
    assert saved is not None and saved.id == rows[0].id


def test_third_member_later_in_same_window_no_second_row(session):
    _group, place = _seed_group(session)
    pe_a = _add_place_event(session, place, "a", "ENTER", T0)
    _add_place_event(session, place, "b", "ENTER", T0 + timedelta(minutes=1))
    _add_fix(session, "c", T0)
    evaluate_group_events(session, pe_a, _Settings(), now=T0 + timedelta(minutes=1))

    pe_c = _add_place_event(session, place, "c", "ENTER", T0 + timedelta(minutes=5))
    rows = evaluate_group_events(session, pe_c, _Settings(), now=T0 + timedelta(minutes=5))

    assert rows == []
    assert len(list(session.scalars(select(GroupPlaceEvent)))) == 1


def test_stale_member_excluded_from_considered(session):
    _group, place = _seed_group(session)
    pe_a = _add_place_event(session, place, "a", "ENTER", T0)
    _add_place_event(session, place, "b", "ENTER", T0 + timedelta(minutes=1))
    # "c" last reported 2 hours before `now` -- stale under the 60-minute default.
    _add_fix(session, "c", T0 - timedelta(hours=2))

    rows = evaluate_group_events(session, pe_a, _Settings(), now=T0 + timedelta(minutes=1))

    assert len(rows) == 1
    assert rows[0].members_considered == 2
    assert rows[0].members_crossed == 2
    assert rows[0].members_stale == 1


def test_all_members_stale_no_row(session):
    _group, place = _seed_group(session)
    pe_a = _add_place_event(session, place, "a", "ENTER", T0)
    now = T0 + timedelta(hours=3)  # everyone's fix (including a's) is now stale

    rows = evaluate_group_events(session, pe_a, _Settings(), now=now)

    assert rows == []
    assert session.scalar(select(GroupPlaceEvent)) is None


def test_any_quorum_fires_on_first_member(session):
    group, place = _seed_group(session, quorum="any")
    pe_a = _add_place_event(session, place, "a", "ENTER", T0)
    _add_fix(session, "b", T0)
    _add_fix(session, "c", T0)

    rows = evaluate_group_events(session, pe_a, _Settings(), now=T0)

    assert len(rows) == 1
    assert rows[0].group_id == group.id
    assert rows[0].members_crossed == 1


def test_hook_failure_never_loses_the_batch(session, monkeypatch):
    """A raising group hook must not roll back the observation it ran on.

    Seeds `a` as already "outside" so the next fix is a real geofence ENTER
    (a first-ever fix only seeds state, per geofence.advance -- it never
    fires an event), which is what makes the group hook actually run.
    """
    _group, place = _seed_group(session)
    session.add(
        PlaceState(
            place_id=place.id,
            device_id="a",
            state="outside",
            streak=0,
            streak_side=None,
            since_observed_at=None,
            last_observation_id=None,
            updated_at=T0,
        )
    )
    session.flush()

    calls: list[int] = []

    def boom(_session, _place_event, _settings):
        calls.append(1)
        raise RuntimeError("group hook exploded")

    monkeypatch.setattr("findplus.ingest._group_events_evaluate", boom)
    result = ingest_observations(session, [_raw_obs("a", T0)])

    assert result.inserted == 1
    assert len(list(session.scalars(select(LocationObservation)))) >= 1
    assert calls == [1]  # the group hook did run, and raising did not lose the batch
    assert session.scalar(select(PlaceEvent)) is not None  # geofence's row survives too


def _raw_obs(device_id: str, observed_at: datetime):
    from findplus.findhub.types import RawObservation

    return RawObservation(
        device_id=device_id,
        device_name=device_id,
        latitude_e7=411000000,
        longitude_e7=-806400000,
        observed_at=observed_at,
        accuracy_meters=30.0,
        source="crowdsourced",
        is_own_report=False,
    )

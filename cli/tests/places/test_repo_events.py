"""places/repo.py: place-event listing, filtering and presence.

Split out of test_repo.py (PRI rule 7, <=300 lines/file); the CRUD and
confirmation-streak tests stayed there. Shared seed helpers live in _helpers.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from findplus.db.models import PlaceEvent, PlaceState
from findplus.groups.repo import create_group
from findplus.places.repo import create_place, current_presence, list_place_events, list_places

from ._helpers import _devices  # noqa: F401  (autouse where imported)
from ._helpers import make_observation as _make_observation


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


def test_list_place_events_group_filter_resolves_members(session):
    """`group_id` filtered on PlaceEvent.group_id, a column nothing writes (E1 CR-C).

    api-contract.md and mcp-tools.md both advertise the parameter, so it returned
    an empty list for every caller. It now resolves the group to its member devices.
    """
    place = create_place(session, name="P1", latitude_e7=0, longitude_e7=0, radius_meters=100)
    group = create_group(session, name="Family", member_ids=["dev1"])
    session.flush()

    base = datetime.now(UTC) - timedelta(minutes=2)
    for device_id, when in (("dev1", base), ("dev2", base + timedelta(minutes=1))):
        session.add(
            PlaceEvent(
                place_id=place.id,
                device_id=device_id,
                event_type="ENTER",
                observed_at=datetime.now(UTC),
                fetched_at=datetime.now(UTC),
                observation_id=_make_observation(session, device_id=device_id, when=when),
                confidence="high",
                distance_meters=1.0,
            )
        )
    session.flush()

    rows = list_place_events(session, group_id=group.id)

    assert [r.device_id for r in rows] == ["dev1"]


def _inside_state(session, place, device_id="dev1"):
    session.add(
        PlaceState(
            place_id=place.id,
            device_id=device_id,
            state="inside",
            streak=0,
            since_observed_at=None,
            last_observation_id=None,
            updated_at=datetime.now(UTC),
        )
    )
    session.flush()


def test_devices_inside(session):
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    _inside_state(session, place)
    _make_observation(session, "dev1", datetime.now(UTC))

    assert list_places(session)[0]._devices_inside == ["dev1"]

    session.get(PlaceState, (place.id, "dev1")).state = "outside"
    session.flush()
    assert list_places(session)[0]._devices_inside == []


def test_a_silent_tracker_stops_being_listed_inside(session):
    """honesty round 3 F1: a place_state only advances when a new fix arrives.

    A tracker that entered Home and then went quiet stayed `inside` for ever,
    so the dashboard read "Home since 3 d" about a tag nobody had heard from.
    honesty.md's presence_stale sentence forbids exactly that reading.
    """
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    _inside_state(session, place)
    _make_observation(session, "dev1", datetime.now(UTC) - timedelta(days=3))

    assert list_places(session)[0]._devices_inside == []

    presence = current_presence(session, device_id="dev1")
    assert [r["state"] for r in presence] == ["unknown"]
    assert presence[0]["stale"] is True


def test_a_reporting_tracker_is_still_inside(session):
    """The control: a fresh fix keeps the place claim."""
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    _inside_state(session, place)
    _make_observation(session, "dev1", datetime.now(UTC) - timedelta(minutes=5))

    assert list_places(session)[0]._devices_inside == ["dev1"]
    presence = current_presence(session, device_id="dev1")
    assert presence[0]["state"] == "inside"
    assert presence[0]["stale"] is False


def test_a_tracker_that_never_reported_is_not_inside(session):
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    _inside_state(session, place)

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

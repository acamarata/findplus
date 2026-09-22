"""api/_widget.py's `_widget_places`: presence-derived device/group badges.

The Places widget (E13 seed, shipped 1.1) reads GET /api/widget's `places`
array rather than a place-specific endpoint, so a badge's icon/colour comes
from the SAME payload's `devices`/`groups` arrays (R-P2-23) -- this module
only has to prove device_ids/group_ids/last_change_at are right, not
re-derive names or colours places.repo never stored anyway.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from findplus.api._widget import _widget_places
from findplus.db.models import PlaceState
from findplus.groups.repo import create_group
from findplus.places.repo import create_place

from ._helpers import _devices  # noqa: F401  (autouse where imported)
from ._helpers import make_observation as _make_observation

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _inside(session, place, device_id, *, since):
    session.add(
        PlaceState(
            place_id=place.id,
            device_id=device_id,
            state="inside",
            streak=1,
            since_observed_at=since,
            last_observation_id=None,
            updated_at=NOW,
        )
    )
    session.flush()


def test_place_with_nobody_inside(session):
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)

    rows = _widget_places(session, NOW)

    assert rows == [
        {
            "id": place.id,
            "name": "Home",
            "device_ids": [],
            "group_ids": [],
            "last_change_at": None,
        }
    ]


def test_present_device_reports_last_change(session):
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    _make_observation(session, "dev1", NOW - timedelta(minutes=2))
    _inside(session, place, "dev1", since=NOW - timedelta(minutes=10))

    rows = _widget_places(session, NOW)

    assert rows[0]["device_ids"] == ["dev1"]
    assert rows[0]["last_change_at"] == "2026-09-22T11:50:00Z"


def test_stale_device_is_not_a_present_badge(session):
    """honesty.PRESENCE_STALE, same rule list_places already applies (round 3 F1)."""
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    _make_observation(session, "dev1", NOW - timedelta(days=3))
    _inside(session, place, "dev1", since=NOW - timedelta(days=3))

    rows = _widget_places(session, NOW)

    assert rows[0]["device_ids"] == []
    assert rows[0]["last_change_at"] is None


def test_a_full_group_is_served_as_a_group_badge(session):
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    group = create_group(session, name="Family", member_ids=["dev1", "dev2"])
    for device_id, minutes_ago in (("dev1", 2), ("dev2", 4)):
        _make_observation(session, device_id, NOW - timedelta(minutes=minutes_ago))
        _inside(session, place, device_id, since=NOW - timedelta(minutes=minutes_ago))

    rows = _widget_places(session, NOW)

    assert rows[0]["group_ids"] == [group.id]
    assert set(rows[0]["device_ids"]) == {"dev1", "dev2"}


def test_a_partial_group_is_not_a_group_badge(session):
    """Showing the group badge for a partial group would claim someone is here

    who is not -- the same bar groups/presence.py's partial verdict holds to.
    """
    place = create_place(session, name="Home", latitude_e7=0, longitude_e7=0, radius_meters=100)
    create_group(session, name="Family", member_ids=["dev1", "dev2"])
    _make_observation(session, "dev1", NOW - timedelta(minutes=2))
    _inside(session, place, "dev1", since=NOW - timedelta(minutes=2))

    rows = _widget_places(session, NOW)

    assert rows[0]["group_ids"] == []
    assert rows[0]["device_ids"] == ["dev1"]


def test_places_are_name_ordered(session):
    create_place(session, name="Zoo", latitude_e7=0, longitude_e7=0, radius_meters=100)
    create_place(session, name="Attic", latitude_e7=1, longitude_e7=1, radius_meters=100)

    rows = _widget_places(session, NOW)

    assert [r["name"] for r in rows] == ["Attic", "Zoo"]

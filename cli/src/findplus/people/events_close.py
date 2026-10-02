"""Arriving somewhere closes the place the person was at before (uat116 #2).

Purpose : A person carried by several trackers arrived at School while still
          "inside" Home: one tracker's own geofence had not confirmed its exit
          yet (D17 needs two outside fixes), so the person state for Home held,
          and "left Home" came 20 minutes late, after the arrival. Being inside
          School means being outside every place that does not overlap it, so
          the arrival closes those places first, with their real crossing time.
Inputs  : The session, the person group, the PersonFix and trackers of this
          evaluation, the places, the device states, the arrival rows just
          written, and the evaluation instant.
Outputs : The EXIT group_place_events rows written (also moves the states).
Constraints: Never commits. Places that overlap (a Home inside a larger
          "Neighbourhood") are left alone: being in one says nothing about the
          other. The EXIT never claims a time later than the arrival, so the
          story always reads "left Home" before "arrived at School".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from findplus.db.models import GroupPlaceEvent
from findplus.db.models_people import PersonPlaceState
from findplus.geo import haversine_meters
from findplus.people.infer import PlaceRef


def disjoint(a: PlaceRef, b: PlaceRef) -> bool:
    """True when the two circles do not touch: inside one means outside the other."""
    d = haversine_meters(
        a.latitude_e7 / 1e7, a.longitude_e7 / 1e7, b.latitude_e7 / 1e7, b.longitude_e7 / 1e7
    )
    return d > a.radius_meters + b.radius_meters


def close_left_places(
    session,
    group,
    places: list[PlaceRef],
    arrivals: list[GroupPlaceEvent],
    as_of: datetime,
    write_exit: Callable[..., GroupPlaceEvent | None],
) -> list[GroupPlaceEvent]:
    """Move every other "inside" place that cannot overlap an arrival to outside.

    `write_exit(place, since, latest)` writes the EXIT row (people/events.py's
    _write_event, capped at `latest`); it returns None when one already exists.
    """
    by_id = {p.id: p for p in places}
    out: list[GroupPlaceEvent] = []
    for arrival in arrivals:
        entered = by_id.get(arrival.place_id)
        if entered is None:
            continue
        for place in places:
            if place.id == entered.id or not disjoint(place, entered):
                continue
            row = session.get(PersonPlaceState, (group.id, place.id))
            if row is None or row.state != "inside":
                continue
            since = row.last_transition_at
            row.state, row.pending_side, row.pending_since = "outside", None, None
            row.last_transition_at, row.since_observed_at = as_of, as_of
            event = write_exit(place, since, arrival.observed_at)
            if event is not None:
                out.append(event)
    return out

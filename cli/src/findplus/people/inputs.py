"""Load a person's trackers from the database into the pure inference engine.

Purpose : The DB half of people/infer.py: each member's recent non-suspect
          fixes (as of a given instant), its role and weight, and the places
          its own geofence state says it is inside.
Inputs  : An open Session, a person/pet Group, a tz-aware `as_of`.
Outputs : MemberIn/PlaceRef lists, a PersonFix, tracker display names.
Constraints: Read only. Only fixes observed at or before `as_of` are used, so a
          late report replayed through the engine sees what was known then.
          Suspect fixes are dropped through people/_quality.py only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Device, DeviceGroup, Group, LocationObservation, Place, PlaceState
from findplus.db.models_people import PERSON_KINDS
from findplus.device_labels import unique_names
from findplus.labels import display_name
from findplus.people import _quality
from findplus.people.infer import InferParams, MemberIn, PersonFix, PlaceRef, TrackerFix, infer
from findplus.people.naming import read_name
from findplus.people.roles import effective_weight


@dataclass(frozen=True)
class Tracker:
    """One member tracker as the people surfaces show it."""

    device_id: str
    name: str
    role: str | None
    #: name (guessed from the tracker name) | set (chosen) | none
    role_source: str
    carry_weight: float | None
    weight: float


def person_groups_of(session: Session, device_id: str) -> list[Group]:
    """The person/pet groups this tracker belongs to (at most one, by trigger)."""
    stmt = (
        select(Group)
        .join(DeviceGroup, DeviceGroup.group_id == Group.id)
        .where(DeviceGroup.device_id == device_id, Group.kind.in_(PERSON_KINDS))
    )
    return list(session.scalars(stmt).all())


def trackers_of(
    session: Session, group_id: int, names: dict[str, str] | None = None
) -> list[Tracker]:
    """Every member with its effective role and weight, by display name."""
    names = names if names is not None else unique_names(session)
    rows = session.execute(
        select(Device.device_id, Device.label, Device.name, Device.role, Device.carry_weight)
        .join(DeviceGroup, DeviceGroup.device_id == Device.device_id)
        .where(DeviceGroup.group_id == group_id)
    ).all()
    out = []
    for r in rows:
        shown = names.get(r.device_id) or r.device_id
        guessed = read_name(r.device_id, display_name(r.label, r.name, r.device_id) or "").role
        role = r.role or guessed
        source = "set" if r.role else ("name" if guessed else "none")
        weight = effective_weight(role, r.carry_weight)
        out.append(Tracker(r.device_id, shown, role, source, r.carry_weight, weight))
    return sorted(out, key=lambda t: (t.name.casefold(), t.device_id))


def load_places(session: Session) -> list[PlaceRef]:
    rows = session.scalars(select(Place).order_by(Place.name)).all()
    return [
        PlaceRef(p.id, p.name, p.kind, p.latitude_e7, p.longitude_e7, p.radius_meters) for p in rows
    ]


def params_for(group: Group) -> InferParams:
    return InferParams(
        stale_after_minutes=group.stale_after_minutes,
        cluster_radius_meters=group.cluster_radius_meters,
    )


def _fixes(session: Session, device_id: str, as_of: datetime, hours: int) -> list:
    """The window's fixes plus the one just before it, oldest first."""
    start = as_of - timedelta(hours=hours)
    window = session.scalars(
        select(LocationObservation)
        .where(
            LocationObservation.device_id == device_id,
            LocationObservation.observed_at >= start,
            LocationObservation.observed_at <= as_of,
        )
        .order_by(LocationObservation.observed_at)
    ).all()
    anchor = session.scalars(
        select(LocationObservation)
        .where(LocationObservation.device_id == device_id, LocationObservation.observed_at < start)
        .order_by(LocationObservation.observed_at.desc())
        .limit(1)
    ).all()
    return [*anchor, *window]


def _to_fix(o: LocationObservation) -> TrackerFix:
    return TrackerFix(
        o.id, o.latitude_e7, o.longitude_e7, o.accuracy_meters, o.observed_at, o.first_fetched_at
    )


def load_members(
    session: Session, trackers: list[Tracker], as_of: datetime, p: InferParams
) -> list[MemberIn]:
    """MemberIn per tracker, suspect fixes removed (people/_quality.py)."""
    rows = {
        t.device_id: _fixes(session, t.device_id, as_of, p.motion_window_hours) for t in trackers
    }
    earliest = min((o.observed_at for obs in rows.values() for o in obs), default=as_of)
    suspect = _quality.suspect_ids(session, list(rows), earliest, as_of)
    inside: dict[str, list[int]] = {}
    for device_id, place_id in session.execute(
        select(PlaceState.device_id, PlaceState.place_id).where(
            PlaceState.device_id.in_(list(rows)), PlaceState.state == "inside"
        )
    ).all():
        inside.setdefault(device_id, []).append(place_id)
    return [
        MemberIn(
            device_id=t.device_id,
            name=t.name,
            role=t.role,
            weight=t.weight,
            fixes=tuple(_to_fix(o) for o in rows[t.device_id] if o.id not in suspect),
            inside_place_ids=tuple(sorted(inside.get(t.device_id, []))),
        )
        for t in trackers
    ]


def infer_person(
    session: Session, group: Group, as_of: datetime, names: dict[str, str] | None = None
) -> tuple[PersonFix, list[Tracker], list[PlaceRef]]:
    """Run the pure engine for one person as of `as_of`."""
    trackers = trackers_of(session, group.id, names)
    params = params_for(group)
    places = load_places(session)
    members = load_members(session, trackers, as_of, params)
    return infer(members, places, as_of, params), trackers, places

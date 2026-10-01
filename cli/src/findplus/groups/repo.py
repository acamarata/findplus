"""Groups repository: CRUD, membership, and presence assembly.

Purpose : Single source of truth for group data and presence gathering,
          shared by api/routes_groups.py and cli/groups.py so validation and
          the DB-to-engine wiring live in exactly one place (DRY, matching
          findplus.places.repo's role for places).
Inputs  : An open Session (caller-owned transaction) plus plain arguments.
Outputs : ORM rows (Group) or a groups.presence.GroupPresence.
Constraints: Never commits. Write functions raise ValueError with an exact
          substring ("not found" / "already exists") so callers map it to an
          HTTP/CLI error without guessing. create_group leaves UNIQUE(name)
          to the caller's IntegrityError, per specs/api-contract.md.
Reuse: session pattern matches findplus.places.repo.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findplus.db.models import (
    Device,
    DeviceGroup,
    Group,
    LocationObservation,
    Place,
    PlaceState,
)
from findplus.device_labels import unique_names
from findplus.groups.place_event_list import list_group_place_events  # re-exported
from findplus.groups.presence import (
    Fix,
    GroupPresence,
    MemberInput,
    MemberStatus,
    group_presence,
    member_status,
)
from findplus.groups.timeline import list_group_timeline  # re-exported, see timeline.py
from findplus.groups.validation import clean_name, validate_group_fields


def list_groups(session: Session) -> list[Group]:
    """Every group, alphabetical, with `_members` (device_id/name/provider) attached."""
    rows = list(session.scalars(select(Group).order_by(Group.name)).all())
    for row in rows:
        row._members = _members_of(session, row.id)
    return rows


def _members_of(session: Session, group_id: int) -> list[dict]:
    stmt = (
        select(Device.device_id, Device.name, Device.provider)
        .join(DeviceGroup, DeviceGroup.device_id == Device.device_id)
        .where(DeviceGroup.group_id == group_id)
        .order_by(Device.name)
    )
    return [
        {"device_id": r.device_id, "name": r.name, "provider": r.provider}
        for r in session.execute(stmt).all()
    ]


def check_member_ids(session: Session, member_ids: list[str]) -> list[str]:
    """Drop repeats (order kept) and refuse an id that is not a known device."""
    unique = list(dict.fromkeys(member_ids))
    for device_id in unique:
        if session.get(Device, device_id) is None:
            raise ValueError(f"device {device_id} not found")
    return unique


def _name_taken(session: Session, name: str, *, except_id: int | None = None) -> bool:
    """Case-insensitive: "kids" and "Kids" are one name to a person reading a list."""
    stmt = select(Group.id).where(func.lower(Group.name) == name.lower())
    if except_id is not None:
        stmt = stmt.where(Group.id != except_id)
    return session.scalar(stmt) is not None


def create_group(
    session: Session,
    *,
    name: str,
    color: str = "#27ae60",
    icon: str = "lucide:users",
    quorum: str = "majority",
    cluster_radius_meters: int = 150,
    stale_after_minutes: int = 90,
    member_ids: list[str] | None = None,
) -> Group:
    validate_group_fields(
        quorum=quorum,
        cluster_radius_meters=cluster_radius_meters,
        stale_after_minutes=stale_after_minutes,
        icon=icon,
    )
    name = clean_name(name)
    if _name_taken(session, name):
        raise ValueError(f"group name {name!r} already exists")
    member_ids = check_member_ids(session, member_ids or [])
    group = Group(
        name=name,
        color=color,
        icon=icon,
        quorum=quorum,
        cluster_radius_meters=cluster_radius_meters,
        stale_after_minutes=stale_after_minutes,
        created_at=datetime.now(UTC),
    )
    session.add(group)
    session.flush()  # IntegrityError on a duplicate name propagates to the caller.
    for device_id in member_ids:
        session.add(DeviceGroup(device_id=device_id, group_id=group.id))
    session.flush()
    group._members = _members_of(session, group.id)
    return group


def update_group(session: Session, group_id: int, **fields) -> Group:
    group = session.get(Group, group_id)
    if group is None:
        raise ValueError(f"group {group_id} not found")
    validate_group_fields(
        quorum=fields.get("quorum"),
        cluster_radius_meters=fields.get("cluster_radius_meters"),
        stale_after_minutes=fields.get("stale_after_minutes"),
        icon=fields.get("icon"),
    )
    if fields.get("name") is not None:
        # Name rules apply only to a name that actually changes: a legacy group
        # (case-variant twin, over 64 chars) must stay editable when the dialog
        # resends its stored name unchanged.
        if fields["name"] == group.name or fields["name"].strip() == group.name:
            del fields["name"]
        else:
            fields["name"] = clean_name(fields["name"])
            if _name_taken(session, fields["name"], except_id=group_id):
                raise ValueError(f"group name {fields['name']!r} already exists")
    for key, value in fields.items():
        if value is not None:
            setattr(group, key, value)
    session.flush()
    group._members = _members_of(session, group.id)
    return group


def delete_group(session: Session, group_id: int) -> None:
    group = session.get(Group, group_id)
    if group is None:
        raise ValueError(f"group {group_id} not found")
    session.delete(group)
    session.flush()


def set_members(session: Session, group_id: int, member_ids: list[str]) -> Group:
    group = session.get(Group, group_id)
    if group is None:
        raise ValueError(f"group {group_id} not found")
    member_ids = check_member_ids(session, member_ids)
    session.query(DeviceGroup).filter(DeviceGroup.group_id == group_id).delete(
        synchronize_session=False
    )
    for device_id in member_ids:
        session.add(DeviceGroup(device_id=device_id, group_id=group_id))
    session.flush()
    group._members = _members_of(session, group.id)
    return group


def _member_inputs(session: Session, group: Group) -> list[MemberInput]:
    members: list[MemberInput] = []
    shown = unique_names(session)
    for (device_id,) in session.execute(
        select(Device.device_id)
        .join(DeviceGroup, DeviceGroup.device_id == Device.device_id)
        .where(DeviceGroup.group_id == group.id)
    ).all():
        # Label-first, like every other surface (UAT2 N2), with an id tail only
        # when another visible tracker shares the name (UAT #7).
        name = shown[device_id]
        # No `observed_at >= cutoff` filter (UAT3 N19): a stale member's last
        # fix is exactly what the UI needs for "no fix for N min", and the old
        # lookback window dropped that row, so member_status() saw last_fix=
        # None instead. The (device_id, observed_at) index keeps this cheap.
        obs = session.scalars(
            select(LocationObservation)
            .where(LocationObservation.device_id == device_id)
            .order_by(LocationObservation.observed_at.desc())
            .limit(2)
        ).all()
        last_fix = _to_fix(device_id, obs[0]) if obs else None
        prev_fix = _to_fix(device_id, obs[1]) if len(obs) > 1 else None
        # Smallest circle first: member_status() reports inside_places[0] (the
        # more specific place), deterministically, every call.
        inside_places = session.scalars(
            select(Place.name)
            .join(PlaceState, PlaceState.place_id == Place.id)
            .where(PlaceState.device_id == device_id, PlaceState.state == "inside")
            .order_by(Place.radius_meters, Place.name)
        ).all()
        members.append(
            MemberInput(
                device_id=device_id,
                name=name,
                last_fix=last_fix,
                prev_fix=prev_fix,
                inside_places=inside_places,
            )
        )
    return members


def _to_fix(device_id: str, obs: LocationObservation) -> Fix:
    return Fix(
        observation_id=obs.id,
        device_id=device_id,
        latitude_e7=obs.latitude_e7,
        longitude_e7=obs.longitude_e7,
        accuracy_meters=obs.accuracy_meters,
        observed_at=obs.observed_at,
        fetched_at=obs.first_fetched_at,
    )


def build_presence(
    session: Session, group: Group, window_minutes: int, movement_threshold_meters: float
) -> tuple[GroupPresence, list[MemberStatus]]:
    """Gather each member's recent fixes and delegate to the pure presence engine.

    Returns the verdict alongside per-member statuses: group_presence()'s
    pinned return shape (specs/engines.md) carries no member list, but the API
    and CLI both need one, so member_status() recomputes it from the same
    inputs rather than duplicating it inside the engine.
    """
    members = _member_inputs(session, group)
    now = datetime.now(UTC)
    statuses = [
        member_status(m, now, group.stale_after_minutes, movement_threshold_meters, window_minutes)
        for m in members
    ]
    presence = group_presence(
        group_id=group.id,
        members=members,
        now=now,
        stale_after_minutes=group.stale_after_minutes,
        cluster_radius_meters=group.cluster_radius_meters,
        movement_threshold_meters=movement_threshold_meters,
        window_minutes=window_minutes,
    )
    return presence, statuses


__all__ = [
    "build_presence",
    "create_group",
    "delete_group",
    "list_group_place_events",
    "list_group_timeline",
    "list_groups",
    "set_members",
    "update_group",
]

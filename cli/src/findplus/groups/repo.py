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

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import (
    Device,
    DeviceGroup,
    Group,
    GroupPlaceEvent,
    LocationObservation,
    Place,
    PlaceState,
)
from findplus.groups.presence import (
    Fix,
    GroupPresence,
    MemberInput,
    MemberStatus,
    group_presence,
    member_status,
)
from findplus.groups.quorum import group_event_note, stale_note_for_count
from findplus.groups.timeline import list_group_timeline  # re-exported, see timeline.py
from findplus.groups.validation import validate_group_fields


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
    for device_id in member_ids or []:
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
    for device_id in member_ids:
        if session.get(Device, device_id) is None:
            raise ValueError(f"device {device_id} not found")
    session.query(DeviceGroup).filter(DeviceGroup.group_id == group_id).delete(
        synchronize_session=False
    )
    for device_id in member_ids:
        session.add(DeviceGroup(device_id=device_id, group_id=group_id))
    session.flush()
    group._members = _members_of(session, group.id)
    return group


def _member_inputs(session: Session, group: Group, window_minutes: int) -> list[MemberInput]:
    lookback = max(window_minutes, group.stale_after_minutes)
    cutoff = datetime.now(UTC) - timedelta(minutes=lookback)
    members: list[MemberInput] = []
    for device_id, name in session.execute(
        select(Device.device_id, Device.name)
        .join(DeviceGroup, DeviceGroup.device_id == Device.device_id)
        .where(DeviceGroup.group_id == group.id)
    ).all():
        obs = list(
            session.scalars(
                select(LocationObservation)
                .where(
                    LocationObservation.device_id == device_id,
                    LocationObservation.observed_at >= cutoff,
                )
                .order_by(LocationObservation.observed_at.desc())
                .limit(2)
            ).all()
        )
        last_fix = _to_fix(device_id, obs[0]) if obs else None
        prev_fix = _to_fix(device_id, obs[1]) if len(obs) > 1 else None
        # Smallest circle first: member_status() reports inside_places[0], so
        # a device standing inside "Home" and inside a wider "Neighbourhood"
        # must name the more specific place, deterministically, every call.
        inside_places = list(
            session.scalars(
                select(Place.name)
                .join(PlaceState, PlaceState.place_id == Place.id)
                .where(PlaceState.device_id == device_id, PlaceState.state == "inside")
                .order_by(Place.radius_meters, Place.name)
            ).all()
        )
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

    Returns the group-level verdict alongside the per-member statuses the
    engine computed internally — group_presence()'s pinned return shape
    (specs/engines.md) carries no member list, but both the API and the CLI
    need one (per-device rows), so it is recomputed here with member_status()
    using the exact same inputs rather than duplicated inside the engine.
    """
    members = _member_inputs(session, group, window_minutes)
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


def _group_place_events_stmt(
    group_id: int | None, place_id: int | None, since: datetime | None, until: datetime | None,
    limit: int,
):  # fmt: skip
    stmt = (
        select(GroupPlaceEvent, Group.name.label("group_name"), Place.name.label("place_name"))
        .join(Group, GroupPlaceEvent.group_id == Group.id)
        .join(Place, GroupPlaceEvent.place_id == Place.id)
    )
    if group_id is not None:
        stmt = stmt.where(GroupPlaceEvent.group_id == group_id)
    if place_id is not None:
        stmt = stmt.where(GroupPlaceEvent.place_id == place_id)
    if since is not None:
        stmt = stmt.where(GroupPlaceEvent.observed_at >= since)
    if until is not None:
        stmt = stmt.where(GroupPlaceEvent.observed_at <= until)
    return stmt.order_by(GroupPlaceEvent.observed_at.desc()).limit(min(limit, 1000))


def _group_place_event_dict(e, group_name: str, place_name: str) -> dict:
    return {
        "id": e.id,
        "group_id": e.group_id,
        "group_name": group_name,
        "place_id": e.place_id,
        "place_name": place_name,
        "event_type": e.event_type,
        "observed_at": e.observed_at,
        "members_crossed": e.members_crossed,
        "members_considered": e.members_considered,
        "members_stale": e.members_stale,
        "confidence": e.confidence,
        # api-contract.md § routes_groups.py pins `note` on this route.
        "note": group_event_note(
            crossed=e.members_crossed,
            considered=e.members_considered,
            event_type=e.event_type,
            place=place_name,
            stale_note=stale_note_for_count(e.members_stale),
        ),
        "notified_at": e.notified_at,
    }


def list_group_place_events(
    session: Session,
    *,
    group_id: int | None = None,
    place_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
) -> list[dict]:
    stmt = _group_place_events_stmt(group_id, place_id, since, until, limit)
    return [
        _group_place_event_dict(row.GroupPlaceEvent, row.group_name, row.place_name)
        for row in session.execute(stmt).all()
    ]


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

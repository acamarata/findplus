"""People repository: persons and pets are groups with kind person/pet (spec § 1.1).

Purpose : Create, convert, list and edit people, and set a tracker's role and
          carry weight. Shared by api/routes_people.py, cli/cmd_people.py and
          the suggestion accept path, so every surface validates the same way.
Inputs  : An open Session (caller-owned transaction) and plain arguments.
Outputs : Group rows with `_trackers` attached; plain dicts for JSON.
Constraints: Never commits. Membership rules (one person per tracker) live in
          groups/membership.py and surface as ValueError("... already belongs
          to ..."), which callers map to 409. A device already in a person is
          never moved by anything here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Device, DeviceGroup, Group
from findplus.db.models_people import PERSON_KINDS
from findplus.device_labels import unique_names
from findplus.groups.membership import check_one_person, flush_checked
from findplus.groups.repo import check_member_ids, create_group, update_group
from findplus.people.inputs import trackers_of
from findplus.people.roles import validate_role, validate_weight

DEFAULT_ICONS = {"person": "lucide:user", "pet": "lucide:paw-print"}


def get_person(session: Session, group_id: int) -> Group:
    group = session.get(Group, group_id)
    if group is None or group.kind not in PERSON_KINDS:
        raise ValueError(f"person {group_id} not found")
    return group


def list_people(session: Session) -> list[Group]:
    """Every person and pet, alphabetical, with `_trackers` attached."""
    names = unique_names(session)
    rows = list(
        session.scalars(
            select(Group).where(Group.kind.in_(PERSON_KINDS)).order_by(Group.name)
        ).all()
    )
    for row in rows:
        row._trackers = trackers_of(session, row.id, names)
    return rows


def apply_roles(session: Session, roles: dict[str, str | None] | None) -> None:
    """Store chosen roles (device_id -> role). None leaves a role to the name guess."""
    for device_id, role in (roles or {}).items():
        device = session.get(Device, device_id)
        if device is None:
            raise ValueError(f"device {device_id} not found")
        device.role = validate_role(role)


def create_person(
    session: Session,
    *,
    name: str,
    kind: str = "person",
    member_ids: list[str] | None = None,
    roles: dict[str, str | None] | None = None,
    color: str | None = None,
    icon: str | None = None,
) -> Group:
    """A new person or pet group holding these trackers."""
    if kind not in PERSON_KINDS:
        raise ValueError("kind must be person or pet")
    extra = {"color": color} if color else {}
    group = create_group(
        session, name=name, kind=kind, member_ids=member_ids or [],
        icon=icon or DEFAULT_ICONS[kind], **extra,
    )  # fmt: skip
    apply_roles(session, roles)
    session.flush()
    group._trackers = trackers_of(session, group.id, unique_names(session))
    return group


def add_members(
    session: Session, group_id: int, member_ids: list[str], roles: dict | None = None
) -> Group:
    """Add trackers to a person (or a set being converted), keeping the rest."""
    group = session.get(Group, group_id)
    if group is None:
        raise ValueError(f"group {group_id} not found")
    member_ids = check_member_ids(session, member_ids)
    current = set(
        session.scalars(select(DeviceGroup.device_id).where(DeviceGroup.group_id == group_id))
    )
    new = [d for d in member_ids if d not in current]
    check_one_person(session, group_id, group.kind, new)
    for device_id in new:
        session.add(DeviceGroup(device_id=device_id, group_id=group_id))
    flush_checked(session)
    apply_roles(session, roles)
    session.flush()
    group._trackers = trackers_of(session, group_id, unique_names(session))
    return group


def convert_group(
    session: Session, group_id: int, kind: str = "person", member_ids: list[str] | None = None,
    roles: dict | None = None,
) -> Group:  # fmt: skip
    """Turn a set into a person/pet ("Turn group Zaid into a person"); rules stay."""
    if kind not in PERSON_KINDS:
        raise ValueError("kind must be person or pet")
    update_group(session, group_id, kind=kind)
    return add_members(session, group_id, member_ids or [], roles)


def set_tracker(session: Session, device_id: str, fields: dict) -> Device:
    """Set role and/or carry_weight on one tracker; an explicit None clears it."""
    device = session.get(Device, device_id)
    if device is None:
        raise ValueError(f"device {device_id} not found")
    if "role" in fields:
        device.role = validate_role(fields["role"])
    if "carry_weight" in fields:
        device.carry_weight = validate_weight(fields["carry_weight"])
    session.flush()
    return device


def tracker_dict(t) -> dict:
    return {
        "device_id": t.device_id,
        "name": t.name,
        "role": t.role,
        "role_source": t.role_source,
        "carry_weight": t.carry_weight,
        "weight": t.weight,
    }


def person_dict(group: Group) -> dict:
    """The JSON shape every people surface returns for one person."""
    return {
        "id": group.id,
        "name": group.name,
        "kind": group.kind,
        "color": group.color,
        "icon": group.icon,
        "stale_after_minutes": group.stale_after_minutes,
        "cluster_radius_meters": group.cluster_radius_meters,
        "trackers": [tracker_dict(t) for t in getattr(group, "_trackers", [])],
    }


def now_dict(session: Session, group: Group, now: datetime | None = None) -> dict:
    """Where the person is now: the § 3 answer plus its sentence."""
    from findplus.people.describe import now_text
    from findplus.people.inputs import infer_person

    now = now or datetime.now(UTC)
    fix, trackers, places = infer_person(session, group, now, unique_names(session))
    iso = fix.observed_at.isoformat() if fix.observed_at else None
    return {
        "confidence": fix.confidence,
        "text": now_text(fix, trackers, places, now, group.name),
        "place_id": fix.place_id,
        "place_name": fix.place_name,
        "relation": fix.relation,
        "lead_device_id": fix.lead_device_id,
        # The lead tracker's own fix, never an average (invariant 5).
        "latitude": fix.lat,
        "longitude": fix.lon,
        "accuracy_meters": fix.accuracy_m,
        "observed_at": iso,
        "age_minutes": int((now - fix.observed_at).total_seconds() // 60) if iso else None,
        "supporters": list(fix.supporters),
        "dissenters": list(fix.dissenters),
        "stale": list(fix.stale),
        "trackers": [
            {"device_id": s.device_id, "motion": s.motion, "score": round(s.score, 3)}
            for s in fix.members
        ],
    }

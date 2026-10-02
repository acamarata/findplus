"""One person per tracker: the API-side check and the trigger's translation.

Purpose : A tracker sits in at most one person/pet group (any number of sets),
          specs/people-and-presence.md § 1.1. Migration 0013's triggers enforce
          it in SQLite; this module checks first so the caller gets a sentence
          naming the tracker and the person, and turns the trigger's
          IntegrityError (a race, or a path that skipped the check) into the
          same ValueError, which the routes map to 409.
Inputs  : A session, the group id (None while creating), its kind, member ids.
Outputs : None, or ValueError whose text contains "already belongs".
Constraints: Never commits. Group.kind is validated here too (no CHECK on the
          column, by design: a CHECK would force a rebuild of `groups`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from findplus.db.models import DeviceGroup, Group
from findplus.db.models_people import GROUP_KINDS, ONE_PERSON_PER_DEVICE, PERSON_KINDS

CONFLICT = "already belongs to"


def validate_kind(kind: str | None) -> str | None:
    if kind is not None and kind not in GROUP_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(GROUP_KINDS)}")
    return kind


def check_one_person(
    session: Session, group_id: int | None, kind: str, member_ids: list[str]
) -> None:
    """Refuse a member that already belongs to a different person or pet."""
    if kind not in PERSON_KINDS or not member_ids:
        return
    stmt = (
        select(DeviceGroup.device_id, Group.name)
        .join(Group, Group.id == DeviceGroup.group_id)
        .where(DeviceGroup.device_id.in_(member_ids), Group.kind.in_(PERSON_KINDS))
    )
    if group_id is not None:
        stmt = stmt.where(Group.id != group_id)
    clash = session.execute(stmt).first()
    if clash is not None:
        raise ValueError(f"tracker {clash.device_id} {CONFLICT} {clash.name}")


def flush_checked(session: Session) -> None:
    """flush(), with the one-person trigger's abort turned into a ValueError."""
    try:
        session.flush()
    except IntegrityError as exc:
        if ONE_PERSON_PER_DEVICE not in str(exc):
            raise
        raise ValueError(f"a tracker {CONFLICT} another person") from exc

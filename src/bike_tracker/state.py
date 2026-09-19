"""Key/value settings stored in the database (device selection, bookkeeping)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from bike_tracker.db.models import Device, Setting

SELECTED_DEVICE_ID = "selected_device_id"


def get_setting(session: Session, key: str, default: str | None = None) -> str | None:
    row = session.get(Setting, key)
    return row.value if row is not None else default


def set_setting(session: Session, key: str, value: str | None) -> None:
    row = session.get(Setting, key)
    now = datetime.now(UTC)
    if row is None:
        session.add(Setting(key=key, value=value, updated_at=now))
    else:
        row.value, row.updated_at = value, now
    session.flush()


def select_device(session: Session, device_id: str) -> Device:
    """Mark one device as the tracked device. Exactly one may be selected."""
    device = session.get(Device, device_id)
    if device is None:
        raise LookupError(
            f"Unknown device {device_id!r}. Run `bike-tracker devices` to refresh the list."
        )
    for other in session.scalars(select(Device).where(Device.is_selected.is_(True))):
        other.is_selected = False
    device.is_selected = True
    set_setting(session, SELECTED_DEVICE_ID, device_id)
    session.flush()
    return device


def get_selected_device(session: Session) -> Device | None:
    device = session.scalar(select(Device).where(Device.is_selected.is_(True)))
    if device is not None:
        return device
    device_id = get_setting(session, SELECTED_DEVICE_ID)
    return session.get(Device, device_id) if device_id else None

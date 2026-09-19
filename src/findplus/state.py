"""Device tracking selection and small key/value settings.

Purpose : Decide which Find Hub devices the daemon polls.
Constraints:
    - Any number of devices may be tracked at once. Tracking N devices means N
      Google requests per poll cycle, so the caller is expected to surface that.
    - `default_device_id` only controls which device the dashboard focuses on
      first; it never restricts what is polled or stored.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Device, Setting

DEFAULT_DEVICE_ID = "default_device_id"


# ------------------------------------------------------------------ settings
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


# ------------------------------------------------------------------ tracking
def track_devices(
    session: Session, device_ids: Iterable[str], *, exclusive: bool = False
) -> list[Device]:
    """Mark devices as tracked.

    `exclusive=True` untracks everything else first, which is how "track only
    these" is expressed. Otherwise the given devices are added to the set.
    """
    ids = list(dict.fromkeys(device_ids))
    known = {d.device_id: d for d in session.scalars(select(Device))}
    missing = [i for i in ids if i not in known]
    if missing:
        raise LookupError(
            f"Unknown device id(s): {', '.join(missing)}. "
            "Run `findplus devices` to refresh the list."
        )

    if exclusive:
        for device in known.values():
            device.is_tracked = False

    tracked = []
    for device_id in ids:
        known[device_id].is_tracked = True
        tracked.append(known[device_id])

    _ensure_default(session)
    session.flush()
    return tracked


def untrack_devices(session: Session, device_ids: Iterable[str]) -> int:
    """Stop polling the given devices. Their history is kept."""
    count = 0
    for device_id in device_ids:
        device = session.get(Device, device_id)
        if device is not None and device.is_tracked:
            device.is_tracked = False
            count += 1
    _ensure_default(session)
    session.flush()
    return count


def track_all(session: Session) -> list[Device]:
    """Track every device currently known to the account."""
    devices = list(session.scalars(select(Device)))
    for device in devices:
        device.is_tracked = True
    _ensure_default(session)
    session.flush()
    return devices


def get_tracked_devices(session: Session) -> list[Device]:
    """Devices the poller should query, in stable name order."""
    return list(
        session.scalars(select(Device).where(Device.is_tracked.is_(True)).order_by(Device.name))
    )


def get_default_device(session: Session) -> Device | None:
    """The device the dashboard focuses on first. Not a polling restriction."""
    device_id = get_setting(session, DEFAULT_DEVICE_ID)
    if device_id:
        device = session.get(Device, device_id)
        if device is not None and device.is_tracked:
            return device
    tracked = get_tracked_devices(session)
    return tracked[0] if tracked else None


def set_default_device(session: Session, device_id: str | None) -> None:
    set_setting(session, DEFAULT_DEVICE_ID, device_id)


def _ensure_default(session: Session) -> None:
    """Keep `default_device_id` pointing at something that is actually tracked."""
    current = get_setting(session, DEFAULT_DEVICE_ID)
    tracked = {d.device_id for d in get_tracked_devices(session)}
    if current not in tracked:
        set_setting(session, DEFAULT_DEVICE_ID, next(iter(sorted(tracked))) if tracked else None)

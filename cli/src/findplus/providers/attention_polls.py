"""Did the newest poll of a provider fail because its sign-in is gone?

Purpose    : Spec in-app-login.md §6 lists two Google lost-sign-in inputs: the
             `auth_revoked` mark and `last_error_type == "auth"` (the poll
             itself was refused). attention.py reads the mark; this module reads
             the newest poll run of the provider's own devices, so a sign-in the
             poller found dead raises the same tray item, banner and deep link
             (r12 #6). The poller stores the class name, so both vocabularies count.
Inputs     : A provider id and when its sign-in was last saved (or None).
Outputs    : `poll_says_signin_needed(provider, signed_in_at)`.
Constraints: One indexed read, never raises (a broken DB answers False). A run
             older than the latest saved sign-in is history, not a loss: the
             banner must clear the moment the person signs in again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

#: error_type values a refused sign-in leaves on a poll run (poller.py, _widget.py).
AUTH_ERROR_TYPES = frozenset(
    {"auth", "AuthRequiredError", "AppleAuthRequiredError", "unauthenticated"}
)


def saved_at(path: Path) -> datetime | None:
    """When a sign-in file was last written (UTC), or None when it is missing."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return None


def _newest_run(provider: str):
    from sqlalchemy import desc, select

    from findplus.db.models import Device, PollRun
    from findplus.db.session import session_scope

    with session_scope() as session:
        run = session.scalar(
            select(PollRun)
            .join(Device, Device.device_id == PollRun.device_id)
            .where(Device.provider == provider)
            .order_by(desc(PollRun.started_at))
            .limit(1)
        )
        return (run.error_type, run.started_at) if run is not None else None


def poll_says_signin_needed(provider: str, signed_in_at: datetime | None) -> bool:
    """True when the provider's newest poll was refused for its sign-in, after `signed_in_at`."""
    try:
        newest = _newest_run(provider)
    except Exception:
        return False
    if newest is None or newest[0] not in AUTH_ERROR_TYPES:
        return False
    started = newest[1]
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return signed_in_at is None or started > signed_in_at

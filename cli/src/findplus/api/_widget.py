"""Helpers behind `GET /api/widget` — the compact feed the macOS widget reads.

Purpose    : Build the widget payload's device rows, group rows, map-preview
             flag and overall state, in one module the widget owns.
Inputs     : A DB session, "now", and the staleness threshold in minutes.
Outputs    : Plain dicts/strings ready for JSON (api-contract.md § /api/widget).
Constraints: No route decorators and no FastAPI import — pure functions, so
             the widget tests can call them without an app. Split out of
             _helpers.py, which had grown past the 300-line file cap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select, text
from sqlalchemy.exc import OperationalError

from findplus.db.models import LocationObservation
from findplus.state import get_setting, get_tracked_devices

from ._time import _iso_z

#: Widget staleness threshold in minutes (D18, the same number groups default to).
#: Served as `stale_after_minutes` on GET /api/widget so the Swift views read one
#: agreed figure instead of hardcoding a second, looser one of their own.
WIDGET_STALE_AFTER_MINUTES = 90

#: `PollRun.error_type` values that put the widget straight into `error`,
#: without waiting for three consecutive failures.
#:
#: api-contract.md § GET /api/widget writes this set as `{auth, decrypt}`, but
#: poller.py has never stored those two words: it stores the exception class
#: name (`AuthRequiredError`, `DecryptionError`) or a provider verdict
#: (`unauthenticated`). Matching only the spec's two words meant a revoked
#: Google session — the one failure the user must act on, and the only one a
#: glance at the widget can prompt — showed as `ok` or `stale` for three poll
#: cycles before `consecutive_failures >= 3` finally fired. Both vocabularies
#: are accepted so the spec's words keep working if the poller ever adopts them.
ERROR_STATE_TYPES = frozenset(
    {
        "auth",
        "decrypt",
        "AuthRequiredError",
        "DecryptionError",
        "unauthenticated",
    }
)


def _place_by_device(session) -> dict[str, str]:
    """Lowest-`place_id` 'inside' place name per device; `{}` before places exist."""
    from findplus.places.repo import current_presence

    try:
        rows = current_presence(session)
    except OperationalError:
        return {}
    inside = sorted((r for r in rows if r["state"] == "inside"), key=lambda r: r["place_id"])
    out: dict[str, str] = {}
    for row in inside:
        out.setdefault(row["device_id"], row["place_name"])
    return out


def _group_by_device(session) -> dict[str, str]:
    """Lowest-`group_id` member group name per device; `{}` before groups exist.

    Raw SQL against the pinned migration-0005 schema (data-model.md), not an
    ORM import: the groups package (E5) was landing concurrently with the
    ticket that wrote this and had not defined its ORM class names yet.
    """
    try:
        rows = session.execute(
            text(
                "SELECT dg.device_id AS device_id, g.name AS name "
                "FROM device_group dg JOIN groups g ON g.id = dg.group_id "
                "ORDER BY g.id"
            )
        ).all()
    except OperationalError:
        return {}
    out: dict[str, str] = {}
    for row in rows:
        out.setdefault(row.device_id, row.name)
    return out


def _group_rows(session) -> list[dict[str, Any]]:
    """`[{id, name, verdict, note}]` for every group; `[]` before groups exist.

    Real presence verdicts come from groups/presence.py (E5) behind
    `GET /api/groups/{id}/presence`; this widget feed reports the honest,
    non-committal "unknown" rather than duplicating that engine here.
    """
    try:
        rows = session.execute(text("SELECT id, name FROM groups ORDER BY id")).all()
    except OperationalError:
        return []
    return [
        {"id": row.id, "name": row.name, "verdict": "unknown", "note": "Not yet evaluated."}
        for row in rows
    ]


def _widget_devices(
    session, now: datetime, stale_after_minutes: int = WIDGET_STALE_AFTER_MINUTES
) -> list[dict[str, Any]]:
    """One row per tracked device that has at least one fix.

    A device whose newest fix is older than `stale_after_minutes` is served
    with `place: null`. honesty.PRESENCE_STALE pins the rule and
    groups/presence.py already applies it: a tag with no recent fix is stale,
    not at a place, so its last known place must never be handed to a caller
    as if the tag were still there.
    """
    places = _place_by_device(session)
    device_groups = _group_by_device(session)
    out: list[dict[str, Any]] = []
    for device in get_tracked_devices(session):
        latest = session.scalar(
            select(LocationObservation)
            .where(LocationObservation.device_id == device.device_id)
            .order_by(desc(LocationObservation.observed_at))
            .limit(1)
        )
        if latest is None:
            continue
        age_minutes = int((now - latest.observed_at).total_seconds() // 60)
        stale = age_minutes > stale_after_minutes
        out.append(
            {
                "device_id": device.device_id,
                "name": device.name,
                "provider": device.provider,
                "last_observed_at": _iso_z(latest.observed_at),
                "age_minutes": age_minutes,
                "latitude": latest.latitude,
                "longitude": latest.longitude,
                "place": None if stale else places.get(device.device_id),
                "group": device_groups.get(device.device_id),
            }
        )
    return out


def _widget_show_map(session, settings) -> bool:
    """Whether the widget should render a map snapshot.

    Per specs/data-model.md: the settings-table key `widget.show_map` wins
    when a row exists (set from the UI); otherwise fall back to the config
    field `Settings.widget_show_map` (env `FINDPLUS_WIDGET_SHOW_MAP`).
    """
    row_value = get_setting(session, "widget.show_map")
    if row_value is not None:
        return row_value == "1"
    return settings.widget_show_map


def _widget_state(
    last_error_type: str | None,
    consecutive_failures: int,
    last_poll_at: datetime | None,
    poll_interval_seconds: float,
) -> str:
    """Exactly `ok`|`stale`|`error` — `down` is rendered client-side, never here."""
    if last_error_type in ERROR_STATE_TYPES or consecutive_failures >= 3:
        return "error"
    if last_poll_at is not None:
        stale_after = 2 * poll_interval_seconds
        if (datetime.now(UTC) - last_poll_at).total_seconds() > stale_after:
            return "stale"
    return "ok"

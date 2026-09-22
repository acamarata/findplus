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

from findplus.config import get_settings
from findplus.db.models import Group, LocationObservation
from findplus.groups.presence import verdict_label
from findplus.groups.repo import build_presence
from findplus.state import get_setting, get_tracked_devices

from ._time import _iso_z

#: Presence lookback window for the widget's group rows, minutes. Matches the
#: default `GET /api/groups/{id}/presence` and `findplus groups presence` use
#: (routes_groups.py, cli/groups.py) so the widget's verdict for a group is
#: the same one the dashboard and CLI would show right now.
WIDGET_GROUP_WINDOW_MINUTES = 60

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
    """`[{id, name, icon, verdict, note}]` for every group; `[]` before groups exist.

    Real presence verdicts, computed the same way `GET /api/groups/{id}/presence`
    and `findplus groups presence` compute them: `groups.repo.build_presence()`
    gathers each member's recent fixes and delegates to the pure
    `groups.presence.group_presence()` engine (widget.md § LargeView renders
    `verdict, note` for exactly this reason — widget.LargeView.swift).
    """
    try:
        groups = session.scalars(select(Group).order_by(Group.id)).all()
    except OperationalError:
        return []
    movement_threshold_meters = get_settings().movement_threshold_meters
    rows: list[dict[str, Any]] = []
    for group in groups:
        presence, _statuses = build_presence(
            session, group, WIDGET_GROUP_WINDOW_MINUTES, movement_threshold_meters
        )
        rows.append(
            {
                "id": group.id,
                "name": group.name,
                "icon": group.icon,
                "verdict": presence.verdict,
                "verdict_label": verdict_label(
                    presence.verdict,
                    diverged=presence.diverged,
                    reporting_count=presence.reporting_count,
                    considered_count=presence.considered_count,
                ),
                "note": presence.note,
            }
        )
    return rows


def _place_members(session) -> dict[int, list[str]]:
    """group_id -> member device_ids, for the widget's full-group place badges.

    Raw SQL against the pinned migration-0005 schema, same reasoning as
    `_group_by_device`.
    """
    try:
        rows = session.execute(text("SELECT group_id, device_id FROM device_group")).all()
    except OperationalError:
        return {}
    out: dict[int, list[str]] = {}
    for row in rows:
        out.setdefault(row.group_id, []).append(row.device_id)
    return out


def _widget_places(
    session, now: datetime, stale_after_minutes: int = WIDGET_STALE_AFTER_MINUTES
) -> list[dict[str, Any]]:
    """`[{id, name, device_ids, group_ids, last_change_at}]`, place-name order.

    Feeds the PlacesWidget widget kind. Presence follows `list_places`'s own
    staleness rule (honesty.PRESENCE_STALE). A group is a badge only when
    EVERY member is inside this place -- a partial group stays its
    individual present members. `WidgetGroup` has no member list, so
    `device_ids` excludes any device already covered by a `group_ids` badge.
    """
    from findplus.places.repo import current_presence, list_places

    try:
        places = list_places(session, stale_after_minutes=stale_after_minutes, now=now)
    except OperationalError:
        return []
    presence = current_presence(session, stale_after_minutes=stale_after_minutes, now=now)
    since_by_place_device = {
        (row["place_id"], row["device_id"]): row["since_observed_at"]
        for row in presence
        if row["state"] == "inside"
    }
    members = _place_members(session)
    out: list[dict[str, Any]] = []
    for place in places:
        present_ids = list(place._devices_inside)
        present = set(present_ids)
        group_ids = sorted(
            gid
            for gid, member_ids in members.items()
            if member_ids and set(member_ids).issubset(present)
        )
        covered = set().union(*(members[gid] for gid in group_ids)) if group_ids else set()
        device_ids = [d for d in present_ids if d not in covered]
        changes = [
            since_by_place_device[(place.id, d)]
            for d in present_ids
            if since_by_place_device.get((place.id, d)) is not None
        ]
        out.append(
            {
                "id": place.id,
                "name": place.name,
                "device_ids": device_ids,
                "group_ids": group_ids,
                "last_change_at": _iso_z(max(changes)) if changes else None,
            }
        )
    return out


def _widget_device_row(
    session,
    device,
    now: datetime,
    stale_after_minutes: int,
    places: dict[str, str],
    device_groups: dict[str, str],
) -> dict[str, Any] | None:
    """One widget device row, or `None` if `device` has no fix yet.

    Split out of `_widget_devices` (E13-CF-P2-13, the 50-line function cap):
    same lookup, same staleness rule, no behaviour change.
    """
    latest = session.scalar(
        select(LocationObservation)
        .where(LocationObservation.device_id == device.device_id)
        .order_by(desc(LocationObservation.observed_at))
        .limit(1)
    )
    if latest is None:
        return None
    age_minutes = int((now - latest.observed_at).total_seconds() // 60)
    stale = age_minutes > stale_after_minutes
    return {
        "device_id": device.device_id,
        "name": device.name,
        "provider": device.provider,
        "last_observed_at": _iso_z(latest.observed_at),
        "age_minutes": age_minutes,
        "latitude": latest.latitude,
        "longitude": latest.longitude,
        "place": None if stale else places.get(device.device_id),
        "group": device_groups.get(device.device_id),
        "label": device.label,
        "icon": device.icon,
        "color": device.color,
    }


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
        row = _widget_device_row(session, device, now, stale_after_minutes, places, device_groups)
        if row is not None:
            out.append(row)
    # Newest fix first. get_tracked_devices() returns stable NAME order, and
    # all three widget views take devices.first, so the headline age, the
    # freshness dot and the large view's map snapshot all belonged to whichever
    # tag sorted first alphabetically. With "Alice bag" 3 days cold and "Zoe
    # tag" 2 minutes old the small widget read "3 d ago"; renaming the tags
    # flipped it to "just now" and hid the cold one entirely. widget.md pins
    # "age of newest fix" and "a snapshot of the newest fix"
    # (E1 honesty round 2 F5).
    out.sort(key=lambda row: row["age_minutes"])
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

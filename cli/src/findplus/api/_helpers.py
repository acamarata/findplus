"""Private helpers shared by the api/ router modules.

Purpose    : Serialization and small computations used by more than one router.
Inputs     : SQLAlchemy rows (Device/LocationObservation/PollRun), timezones, settings.
Outputs    : Plain dicts ready for JSON, or parsed date/range values.
Constraints: No route decorators here — pure functions only, so each router can
             import exactly what it needs without pulling in FastAPI route state.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, func, select, text
from sqlalchemy.exc import OperationalError

from findplus.db.models import LocationObservation, PollRun
from findplus.state import get_setting, get_tracked_devices
from findplus.timeline import day_bounds_utc, observation_count_between


def _device_summary(session, device, zone, now, settings) -> dict[str, Any]:
    """Per-device headline figures for the dashboard."""
    latest = session.scalar(
        select(LocationObservation)
        .where(LocationObservation.device_id == device.device_id)
        .order_by(desc(LocationObservation.observed_at))
        .limit(1)
    )
    total = session.scalar(
        select(func.count(LocationObservation.id)).where(
            LocationObservation.device_id == device.device_id
        )
    )
    start_utc, end_utc = day_bounds_utc(now.astimezone(zone).date(), zone)
    today = observation_count_between(session, device.device_id, start_utc, end_utc)
    last_run = session.scalar(
        select(PollRun)
        .where(PollRun.device_id == device.device_id)
        .order_by(desc(PollRun.started_at))
        .limit(1)
    )
    return {
        "device_id": device.device_id,
        "name": device.name,
        "is_tracked": device.is_tracked,
        "latest_observation": _serialize_latest(latest, zone, now),
        "observations_today": today,
        "observations_total": int(total or 0),
        "last_poll": _serialize_run(last_run, zone),
    }


def _newest(summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The most recent observation across a set of device summaries."""
    candidates = [s["latest_observation"] for s in summaries if s["latest_observation"]]
    if not candidates:
        return None
    return max(candidates, key=lambda o: o["observed_at_utc"])


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid date {value!r}, expected YYYY-MM-DD."
        ) from exc


def _resolve_range(day, start, end, zone) -> tuple[datetime, datetime, str]:
    """Resolve day / start+end / neither (= all history) into a UTC interval."""
    if day:
        target = _parse_day(day)
        s, e = day_bounds_utc(target, zone)
        return s, e, target.isoformat()
    if start or end:
        s_date = _parse_day(start) or date(1970, 1, 1)
        e_date = _parse_day(end) or datetime.now(zone).date()
        s, _ = day_bounds_utc(s_date, zone)
        _, e = day_bounds_utc(e_date, zone)
        return s, e, f"{s_date.isoformat()}_to_{e_date.isoformat()}"
    return (
        datetime(1970, 1, 1, tzinfo=UTC),
        datetime.now(UTC) + timedelta(days=1),
        "all",
    )


def _serialize_latest(obs, zone, now) -> dict[str, Any] | None:
    if obs is None:
        return None
    age = (now - obs.observed_at).total_seconds()
    return {
        "id": obs.id,
        "device_id": obs.device_id,
        "device_name": obs.device_name,
        "latitude": obs.latitude,
        "longitude": obs.longitude,
        "accuracy_meters": obs.accuracy_meters,
        "source": obs.source,
        "battery_level": obs.battery_level,
        "times_returned": obs.times_returned,
        "observed_at_utc": obs.observed_at.isoformat(),
        "observed_at_local": obs.observed_at.astimezone(zone).isoformat(),
        "fetched_at_utc": obs.first_fetched_at.isoformat(),
        "fetched_at_local": obs.first_fetched_at.astimezone(zone).isoformat(),
        "age_seconds": age,
        "retrieval_lag_seconds": (obs.first_fetched_at - obs.observed_at).total_seconds(),
    }


def _serialize_run(run, zone) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "started_at_utc": run.started_at.isoformat(),
        "started_at_local": run.started_at.astimezone(zone).isoformat(),
        "finished_at_utc": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "observations_returned": run.observations_returned,
        "observations_new": run.observations_new,
        "error_type": run.error_type,
        "error_message": run.error_message,
    }


def _poller_appears_live(last_run, settings) -> bool:
    """Heuristic: a poll within ~2.5 intervals means the daemon is alive."""
    if last_run is None:
        return False
    window = settings.effective_poll_interval_minutes * 60 * 2.5
    return (datetime.now(UTC) - last_run.started_at).total_seconds() < window


def _iso_z(dt: datetime | None) -> str | None:
    """UTC instant with a literal Z suffix.

    Built with strftime, never by concatenating "Z" onto an already
    offset-suffixed `isoformat()` string (that doubles up as "+00:00Z").
    """
    if dt is None:
        return None
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _consecutive_failures(session, limit: int = 50) -> int:
    """Trailing PollRuns with a non-ok status, newest first, stopping at the first ok."""
    runs = session.scalars(select(PollRun).order_by(desc(PollRun.started_at)).limit(limit))
    count = 0
    for run in runs:
        if run.status in ("ok", "no_location"):
            break
        count += 1
    return count


def _provider_health() -> list[dict[str, Any]]:
    """One `{name, available, authenticated}` row per installed provider.

    Never raises: a broken provider (import error, probe exception) is
    reported unavailable/unauthenticated instead of 500ing the caller.
    """
    from findplus.providers.base import available_providers, get_provider

    rows: list[dict[str, Any]] = []
    for name in available_providers():
        try:
            provider = get_provider(name)
            available, _reason = provider.is_available()
            authenticated = provider.is_authenticated() if available else False
        except Exception:
            available, authenticated = False, False
        rows.append({"name": name, "available": available, "authenticated": authenticated})
    return rows


def _alerts_configured(settings) -> bool:
    """True if a Telegram bot token or webhook URL is saved in alerts.json."""
    path = settings.alerts_file
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    channels = data.get("channels", {})
    return bool(channels.get("telegram", {}).get("bot_token")) or bool(
        channels.get("webhook", {}).get("url")
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
    ORM import: the groups package (E5) is landing concurrently with this
    ticket and had not defined its ORM class names yet when this was written.
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


def _widget_devices(session, now: datetime) -> list[dict[str, Any]]:
    """One row per tracked device that has at least one fix."""
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
        out.append(
            {
                "device_id": device.device_id,
                "name": device.name,
                "provider": device.provider,
                "last_observed_at": _iso_z(latest.observed_at),
                "age_minutes": int((now - latest.observed_at).total_seconds() // 60),
                "latitude": latest.latitude,
                "longitude": latest.longitude,
                "place": places.get(device.device_id),
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
    if last_error_type in {"auth", "decrypt"} or consecutive_failures >= 3:
        return "error"
    if last_poll_at is not None:
        stale_after = 2 * poll_interval_seconds
        if (datetime.now(UTC) - last_poll_at).total_seconds() > stale_after:
            return "stale"
    return "ok"

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
from sqlalchemy import desc, func, select

from findplus.db.models import LocationObservation, PollRun
from findplus.timeline import day_bounds_utc, observation_count_between

# Re-exported so the routers keep their single `from ._helpers import ...`
# line. `_iso_z` moved to _time.py and the widget block to _widget.py when
# this module outgrew the 300-line file cap (PRI hard rule 7).
from ._time import _iso_z
from ._widget import (
    WIDGET_STALE_AFTER_MINUTES,
    _group_rows,
    _widget_devices,
    _widget_show_map,
    _widget_state,
)

__all__ = [
    "WIDGET_STALE_AFTER_MINUTES",
    "_alerts_configured",
    "_consecutive_failures",
    "_device_summary",
    "_group_rows",
    "_iso_z",
    "_newest",
    "_parse_day",
    "_poller_appears_live",
    "_provider_health",
    "_resolve_range",
    "_serialize_latest",
    "_serialize_run",
    "_widget_devices",
    "_widget_show_map",
    "_widget_state",
]


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

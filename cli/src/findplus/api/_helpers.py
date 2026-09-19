"""Private helpers shared by the api/ router modules.

Purpose    : Serialization and small computations used by more than one router.
Inputs     : SQLAlchemy rows (Device/LocationObservation/PollRun), timezones, settings.
Outputs    : Plain dicts ready for JSON, or parsed date/range values.
Constraints: No route decorators here — pure functions only, so each router can
             import exactly what it needs without pulling in FastAPI route state.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, func, select

from findplus.db.models import LocationObservation, PollRun
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

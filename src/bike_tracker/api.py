"""Local REST API + static UI host.

Purpose : Serve the dashboard and its data to a browser on this machine only.
Constraints:
    - Binds to 127.0.0.1. No analytics, telemetry, cookies or third-party scripts.
    - Reading this API never queries Google. The browser may poll it every ~45s;
      Google is queried only by the server-side poller on its own interval.
    - `/api/poll-now` is the single endpoint that can trigger a Google request,
      and it is POST-only and rate-limited.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, select

from bike_tracker import __version__
from bike_tracker.config import get_settings
from bike_tracker.db.migrate import current_revision, is_up_to_date
from bike_tracker.db.models import Device, LocationObservation, PollRun
from bike_tracker.db.session import session_scope
from bike_tracker.exporters import MEDIA_TYPES, export
from bike_tracker.findhub.bootstrap import describe_stored_auth
from bike_tracker.logging_setup import get_logger
from bike_tracker.state import get_selected_device, select_device
from bike_tracker.timeline import (
    day_bounds_utc,
    day_timeline,
    days_with_data,
    fetch_observations,
    local_zone,
    observation_count_between,
)

log = get_logger(__name__)
STATIC_DIR = Path(__file__).parent / "web" / "static"

FIND_HUB_NOTICE = (
    "This history consists of locations reported through Google's Find Hub network. "
    "Moto Tag uses nearby participating Android devices to report its location. "
    "Location updates can therefore be delayed, sparse, or unavailable, and this "
    "application should not be treated as real-time emergency or child-safety GPS tracking."
)

#: Guards manual polls so the UI cannot be used to hammer Google.
_manual_poll_lock = threading.Lock()
_last_manual_poll: datetime | None = None
MANUAL_POLL_COOLDOWN = timedelta(seconds=60)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="bike-tracker",
        version=__version__,
        description="Local Find Hub location history. Not for emergency use.",
        docs_url="/api/docs",
        redoc_url=None,
    )

    def tz(name: str | None = None):
        return local_zone(name)

    # ------------------------------------------------------------- meta
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "schema_revision": current_revision(),
            "schema_up_to_date": is_up_to_date(),
            "timezone": str(tz()),
            "notice": FIND_HUB_NOTICE,
        }

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "poll_interval_minutes": settings.effective_poll_interval_minutes,
            "movement_threshold_meters": settings.movement_threshold_meters,
            "gap_threshold_minutes": settings.gap_threshold_minutes,
            "retention_days": settings.retention_days,
            "ui_refresh_seconds": settings.ui_refresh_seconds,
            "timezone": str(tz()),
            "notice": FIND_HUB_NOTICE,
            "auth": describe_stored_auth(),
        }

    # ---------------------------------------------------------- devices
    @app.get("/api/devices")
    def devices() -> dict[str, Any]:
        with session_scope() as session:
            rows = list(session.scalars(select(Device).order_by(Device.name)))
            selected = get_selected_device(session)
            return {
                "selected_device_id": selected.device_id if selected else None,
                "devices": [
                    {
                        "device_id": d.device_id,
                        "name": d.name,
                        "is_selected": d.is_selected,
                        "first_seen_at": d.first_seen_at.isoformat(),
                        "last_seen_at": d.last_seen_at.isoformat(),
                    }
                    for d in rows
                ],
            }

    @app.post("/api/devices/select")
    def choose_device(device_id: str = Body(..., embed=True)) -> dict[str, Any]:
        with session_scope() as session:
            try:
                device = select_device(session, device_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {"selected_device_id": device.device_id, "name": device.name}

    # ----------------------------------------------------------- status
    @app.get("/api/status")
    def status(timezone: str | None = Query(default=None)) -> dict[str, Any]:
        zone = tz(timezone)
        now = datetime.now(UTC)
        with session_scope() as session:
            device = get_selected_device(session)
            device_id = device.device_id if device else None

            latest = session.scalar(
                select(LocationObservation)
                .where(
                    LocationObservation.device_id == device_id
                    if device_id
                    else LocationObservation.id.isnot(None)
                )
                .order_by(desc(LocationObservation.observed_at))
                .limit(1)
            )
            last_run = session.scalar(select(PollRun).order_by(desc(PollRun.started_at)).limit(1))
            last_ok = session.scalar(
                select(PollRun)
                .where(PollRun.status.in_(("ok", "no_location")))
                .order_by(desc(PollRun.started_at))
                .limit(1)
            )
            total = session.scalar(
                select(func.count(LocationObservation.id)).where(
                    LocationObservation.device_id == device_id
                    if device_id
                    else LocationObservation.id.isnot(None)
                )
            )
            start_utc, end_utc = day_bounds_utc(datetime.now(zone).date(), zone)
            today_count = observation_count_between(session, device_id, start_utc, end_utc)

            return {
                "device": (
                    {"device_id": device.device_id, "name": device.name} if device else None
                ),
                "latest_observation": _serialize_latest(latest, zone, now),
                "last_poll": _serialize_run(last_run, zone),
                "last_successful_poll": _serialize_run(last_ok, zone),
                "poller_running": _poller_appears_live(last_run, settings),
                "observations_today": today_count,
                "observations_total": int(total or 0),
                "poll_interval_minutes": settings.effective_poll_interval_minutes,
                "timezone": str(zone),
                "server_time": now.astimezone(zone).isoformat(),
                "notice": FIND_HUB_NOTICE,
            }

    # --------------------------------------------------------- timeline
    @app.get("/api/timeline")
    def timeline(
        day: str | None = Query(default=None, description="YYYY-MM-DD, local date"),
        device_id: str | None = Query(default=None),
        movement_threshold_meters: float | None = Query(default=None, ge=0),
        gap_threshold_minutes: float | None = Query(default=None, ge=0),
        timezone: str | None = Query(default=None),
    ) -> dict[str, Any]:
        zone = tz(timezone)
        target = _parse_day(day) or datetime.now(zone).date()
        with session_scope() as session:
            resolved = device_id or _selected_id(session)
            result = day_timeline(
                session,
                resolved,
                target,
                tz=zone,
                movement_threshold_meters=(
                    settings.movement_threshold_meters
                    if movement_threshold_meters is None
                    else movement_threshold_meters
                ),
                gap_threshold_minutes=(
                    settings.gap_threshold_minutes
                    if gap_threshold_minutes is None
                    else gap_threshold_minutes
                ),
            )
            return result.to_dict()

    @app.get("/api/days")
    def days(
        device_id: str | None = Query(default=None), timezone: str | None = Query(default=None)
    ) -> dict[str, Any]:
        zone = tz(timezone)
        with session_scope() as session:
            resolved = device_id or _selected_id(session)
            return {"days": days_with_data(session, resolved, zone), "timezone": str(zone)}

    @app.get("/api/latest")
    def latest(timezone: str | None = Query(default=None)) -> dict[str, Any]:
        """Newest stored observation. Reads local history; does not query Google."""
        zone = tz(timezone)
        now = datetime.now(UTC)
        with session_scope() as session:
            device_id = _selected_id(session)
            obs = session.scalar(
                select(LocationObservation)
                .where(
                    LocationObservation.device_id == device_id
                    if device_id
                    else LocationObservation.id.isnot(None)
                )
                .order_by(desc(LocationObservation.observed_at))
                .limit(1)
            )
            if obs is None:
                raise HTTPException(status_code=404, detail="No observations recorded yet.")
            return _serialize_latest(obs, zone, now) or {}

    @app.get("/api/poll-runs")
    def poll_runs(limit: int = Query(default=25, ge=1, le=200)) -> dict[str, Any]:
        zone = tz()
        with session_scope() as session:
            rows = list(
                session.scalars(select(PollRun).order_by(desc(PollRun.started_at)).limit(limit))
            )
            return {"runs": [_serialize_run(r, zone) for r in rows]}

    @app.post("/api/poll-now")
    def poll_now() -> dict[str, Any]:
        """Trigger one immediate Find Hub query. Rate-limited to protect the account."""
        global _last_manual_poll
        with _manual_poll_lock:
            now = datetime.now(UTC)
            if _last_manual_poll and now - _last_manual_poll < MANUAL_POLL_COOLDOWN:
                wait = (MANUAL_POLL_COOLDOWN - (now - _last_manual_poll)).total_seconds()
                raise HTTPException(
                    status_code=429,
                    detail=f"Manual polls are limited to one per minute. Try again in {wait:.0f}s.",
                )
            _last_manual_poll = now

        from bike_tracker.poller import poll_once

        outcome = poll_once()
        return {
            "status": outcome.status,
            "observations_returned": outcome.received,
            "observations_new": outcome.inserted,
            "duplicates": outcome.duplicates,
            "error": outcome.error_message,
        }

    # ---------------------------------------------------------- exports
    @app.get("/api/export")
    def export_history(
        fmt: str = Query(default="csv", pattern="^(csv|json|gpx|kml)$"),
        day: str | None = Query(default=None),
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        device_id: str | None = Query(default=None),
        timezone: str | None = Query(default=None),
    ):
        zone = tz(timezone)
        with session_scope() as session:
            resolved = device_id or _selected_id(session)
            start_utc, end_utc, label = _resolve_range(day, start, end, zone)
            rows = fetch_observations(session, resolved, start_utc, end_utc)
            body = export(fmt, rows, zone, name=f"Bike history {label}")
        filename = f"bike-history-{label}.{fmt}"
        return PlainTextResponse(
            content=body,
            media_type=MEDIA_TYPES[fmt],
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # -------------------------------------------------------- retention
    @app.post("/api/history/delete-before")
    def delete_before(
        before: str = Body(..., embed=True, description="YYYY-MM-DD, local date"),
        confirm: bool = Body(default=False, embed=True),
    ) -> dict[str, Any]:
        """Delete observations older than a date. Requires explicit confirmation."""
        zone = tz()
        target = _parse_day(before)
        if target is None:
            raise HTTPException(status_code=400, detail="`before` must be YYYY-MM-DD.")
        cutoff_utc, _ = day_bounds_utc(target, zone)

        with session_scope() as session:
            doomed = session.scalar(
                select(func.count(LocationObservation.id)).where(
                    LocationObservation.observed_at < cutoff_utc
                )
            )
            if not confirm:
                return {
                    "deleted": 0,
                    "would_delete": int(doomed or 0),
                    "cutoff_utc": cutoff_utc.isoformat(),
                    "message": "Dry run. Re-send with confirm=true to delete.",
                }
            session.query(LocationObservation).filter(
                LocationObservation.observed_at < cutoff_utc
            ).delete(synchronize_session=False)
            log.warning("history_deleted", before=before, count=int(doomed or 0))
            return {
                "deleted": int(doomed or 0),
                "cutoff_utc": cutoff_utc.isoformat(),
                "message": f"Deleted {doomed} observation(s) before {before}.",
            }

    # ------------------------------------------------------------- UI
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


# ------------------------------------------------------------ helpers
def _selected_id(session) -> str | None:
    device = get_selected_device(session)
    return device.device_id if device else None


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


app = create_app()

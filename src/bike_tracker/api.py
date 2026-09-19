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

from fastapi import Body, Cookie, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, select

from bike_tracker import __version__
from bike_tracker.appsettings import (
    clear_pin,
    load_settings,
    save_idle_minutes,
    save_pin,
    save_theme,
    set_lock_enabled,
)
from bike_tracker.config import get_settings
from bike_tracker.db.migrate import current_revision, is_up_to_date
from bike_tracker.db.models import Device, LocationObservation, PollRun
from bike_tracker.db.session import session_scope
from bike_tracker.exporters import MEDIA_TYPES, export
from bike_tracker.findhub.bootstrap import describe_stored_auth
from bike_tracker.logging_setup import get_logger
from bike_tracker.security import MIN_PIN_LENGTH, SessionStore, hash_pin, verify_pin
from bike_tracker.state import (
    get_default_device,
    get_tracked_devices,
    set_default_device,
    track_all,
    track_devices,
    untrack_devices,
)
from bike_tracker.timeline import (
    day_bounds_utc,
    days_with_data,
    fetch_observations,
    local_zone,
    multi_day_timeline,
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

SESSION_COOKIE = "bike_tracker_session"

#: Endpoints reachable while the app is locked. Everything else 401s.
#: The lock is enforced HERE, server-side — hiding the UI would leave the data
#: one `curl` away.
_UNGATED_PATHS = frozenset({"/api/lock/status", "/api/lock/unlock", "/api/health"})

#: Guards manual polls so the UI cannot be used to hammer Google.
_manual_poll_lock = threading.Lock()
_last_manual_poll: datetime | None = None
MANUAL_POLL_COOLDOWN = timedelta(seconds=60)


def create_app(sessions: SessionStore | None = None) -> FastAPI:
    settings = get_settings()
    sessions = sessions or SessionStore()
    app = FastAPI(
        title="bike-tracker",
        version=__version__,
        description="Local Find Hub location history. Not for emergency use.",
        docs_url="/api/docs",
        redoc_url=None,
    )

    def tz(name: str | None = None):
        return local_zone(name)

    def current_lock_state():
        """(is_locked_overall, AppSettings). Cheap enough to call per request."""
        with session_scope() as session:
            app_settings = load_settings(session)
        return app_settings.lock_active, app_settings

    def sync_idle_timeout(app_settings) -> None:
        sessions.idle_timeout_seconds = app_settings.idle_minutes * 60

    @app.middleware("http")
    async def enforce_app_lock(request: Request, call_next):
        """Return 401 for every gated API path while the app is locked.

        Static assets and the shell page still load — they render the lock
        screen — but no location data crosses this boundary until unlocked.
        """
        path = request.url.path
        if not path.startswith("/api/") or path in _UNGATED_PATHS:
            return await call_next(request)

        lock_active, app_settings = current_lock_state()
        if not lock_active:
            return await call_next(request)

        sync_idle_timeout(app_settings)
        token = request.cookies.get(SESSION_COOKIE)
        if sessions.is_valid(token):
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Locked. Enter your PIN to continue.", "locked": True},
        )

    # ------------------------------------------------------------- app lock
    @app.get("/api/lock/status")
    def lock_status(
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> dict[str, Any]:
        """Whether the app is locked right now. Always reachable."""
        lock_active, app_settings = current_lock_state()
        sync_idle_timeout(app_settings)
        unlocked = not lock_active or sessions.is_valid(session_token, touch=False)
        return {
            "lock_configured": app_settings.pin_configured,
            "lock_enabled": app_settings.lock_enabled,
            "locked": bool(lock_active and not unlocked),
            "idle_minutes": app_settings.idle_minutes,
            "theme": app_settings.theme,
            "retry_after_seconds": round(sessions.seconds_until_retry()),
            "attempts_remaining": sessions.attempts_remaining(),
        }

    @app.post("/api/lock/unlock")
    def unlock(response: Response, pin: str = Body(..., embed=True)) -> dict[str, Any]:
        """Exchange a correct PIN for a session cookie. Rate-limited."""
        wait = sessions.seconds_until_retry()
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Too many incorrect attempts. Try again in {wait:.0f} seconds.",
            )

        lock_active, app_settings = current_lock_state()
        if not lock_active:
            return {"unlocked": True, "note": "The app lock is not enabled."}

        if not verify_pin(pin, app_settings.pin_salt or "", app_settings.pin_hash or ""):
            sessions.record_failure()
            log.warning("unlock_failed", attempts_remaining=sessions.attempts_remaining())
            raise HTTPException(
                status_code=401,
                detail=(
                    f"Incorrect PIN. {sessions.attempts_remaining()} attempt(s) "
                    "before a 60-second lockout."
                ),
            )

        sessions.clear_failures()
        sync_idle_timeout(app_settings)
        token = sessions.create()
        response.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            samesite="strict",
            max_age=None,
            path="/",
        )
        log.info("unlocked")
        return {"unlocked": True, "idle_minutes": app_settings.idle_minutes}

    @app.post("/api/lock/lock")
    def lock_now(
        response: Response,
        session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> dict[str, Any]:
        """Lock immediately (manual button, or the client's idle timer)."""
        sessions.revoke(session_token)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"locked": True}

    @app.get("/api/lock/requirements")
    def lock_requirements() -> dict[str, Any]:
        return {
            "min_pin_length": MIN_PIN_LENGTH,
            "caveat": (
                "The app lock stops someone from browsing this dashboard. It does "
                "NOT encrypt the database — anyone with access to this user account "
                "or the disk can still read the history file directly. Use FileVault "
                "for protection at rest."
            ),
        }

    # ------------------------------------------------------------- settings
    @app.get("/api/settings")
    def read_settings() -> dict[str, Any]:
        with session_scope() as session:
            return load_settings(session).public()

    @app.put("/api/settings")
    def write_settings(
        theme: str | None = Body(default=None, embed=True),
        idle_minutes: int | None = Body(default=None, embed=True),
        lock_enabled: bool | None = Body(default=None, embed=True),
    ) -> dict[str, Any]:
        with session_scope() as session:
            try:
                if theme is not None:
                    save_theme(session, theme)
                if idle_minutes is not None:
                    save_idle_minutes(session, idle_minutes)
                if lock_enabled is not None:
                    current = load_settings(session)
                    if lock_enabled and not current.pin_configured:
                        raise HTTPException(
                            status_code=400,
                            detail="Set a PIN before enabling the app lock.",
                        )
                    set_lock_enabled(session, lock_enabled)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            updated = load_settings(session)
        sync_idle_timeout(updated)
        return updated.public()

    @app.post("/api/settings/pin")
    def set_pin(
        response: Response,
        new_pin: str = Body(..., embed=True),
        current_pin: str | None = Body(default=None, embed=True),
    ) -> dict[str, Any]:
        """Set or change the PIN. Changing it requires the existing one.

        A credential change revokes every existing session, then immediately
        re-issues one to THIS browser. Other devices are signed out; the person
        who just set the PIN is not locked out of the window they set it in.
        """
        with session_scope() as session:
            existing = load_settings(session)
            if existing.pin_configured and not verify_pin(
                current_pin or "", existing.pin_salt or "", existing.pin_hash or ""
            ):
                raise HTTPException(status_code=403, detail="Current PIN is incorrect.")
            try:
                salt, digest = hash_pin(new_pin)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            save_pin(session, salt, digest)
            updated = load_settings(session)

        sessions.revoke_all()
        sync_idle_timeout(updated)
        response.set_cookie(
            SESSION_COOKIE,
            sessions.create(),
            httponly=True,
            samesite="strict",
            max_age=None,
            path="/",
        )
        log.info("pin_updated")
        return updated.public()

    @app.delete("/api/settings/pin")
    def remove_pin(current_pin: str = Query(...)) -> dict[str, Any]:
        """Remove the PIN and disable the lock. Requires the current PIN."""
        with session_scope() as session:
            existing = load_settings(session)
            if not existing.pin_configured:
                return existing.public()
            if not verify_pin(current_pin, existing.pin_salt or "", existing.pin_hash or ""):
                raise HTTPException(status_code=403, detail="Current PIN is incorrect.")
            clear_pin(session)
            updated = load_settings(session)
        sessions.revoke_all()
        log.warning("pin_removed")
        return updated.public()

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
            default = get_default_device(session)
            tracked = [d for d in rows if d.is_tracked]
            interval = settings.effective_poll_interval_minutes
            return {
                "default_device_id": default.device_id if default else None,
                "tracked_count": len(tracked),
                "requests_per_hour": round(len(tracked) * 60 / interval, 1) if interval else None,
                "devices": [
                    {
                        "device_id": d.device_id,
                        "name": d.name,
                        "is_tracked": d.is_tracked,
                        "observation_count": int(
                            session.scalar(
                                select(func.count(LocationObservation.id)).where(
                                    LocationObservation.device_id == d.device_id
                                )
                            )
                            or 0
                        ),
                        "first_seen_at": d.first_seen_at.isoformat(),
                        "last_seen_at": d.last_seen_at.isoformat(),
                    }
                    for d in rows
                ],
            }

    @app.post("/api/devices/refresh")
    def refresh_devices() -> dict[str, Any]:
        """Re-query Find Hub for the account's device list."""
        from bike_tracker.findhub.client import FindHubClient
        from bike_tracker.ingest import upsert_device

        try:
            found = FindHubClient(settings).list_devices()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        with session_scope() as session:
            for d in found:
                upsert_device(session, d.device_id, d.name)
        return {"found": len(found)}

    @app.post("/api/devices/track")
    def set_tracked(
        device_ids: list[str] | None = Body(default=None, embed=True),
        all_devices: bool = Body(default=False, embed=True),
    ) -> dict[str, Any]:
        """Replace the tracked set. `all_devices=true` tracks everything."""
        with session_scope() as session:
            try:
                tracked = (
                    track_all(session)
                    if all_devices
                    else track_devices(session, device_ids or [], exclusive=True)
                )
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if not all_devices and not device_ids:
                untrack_devices(session, [d.device_id for d in get_tracked_devices(session)])
                tracked = []
            interval = settings.effective_poll_interval_minutes
            return {
                "tracked": [{"device_id": d.device_id, "name": d.name} for d in tracked],
                "tracked_count": len(tracked),
                "requests_per_hour": round(len(tracked) * 60 / interval, 1) if interval else None,
            }

    @app.post("/api/devices/default")
    def choose_default(device_id: str | None = Body(default=None, embed=True)) -> dict[str, Any]:
        """Set which device the dashboard focuses on first."""
        with session_scope() as session:
            set_default_device(session, device_id)
            return {"default_device_id": device_id}

    # ----------------------------------------------------------- status
    @app.get("/api/status")
    def status(
        device_id: str | None = Query(default=None),
        timezone: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Overall health plus a per-device summary.

        `device_id` narrows the headline figures to one tracker; without it they
        aggregate across every device that has history.
        """
        zone = tz(timezone)
        now = datetime.now(UTC)
        with session_scope() as session:
            tracked = get_tracked_devices(session)
            default = get_default_device(session)
            all_devices = list(session.scalars(select(Device).order_by(Device.name)))

            per_device = [
                _device_summary(session, device, zone, now, settings) for device in all_devices
            ]

            scoped = [d for d in per_device if device_id is None or d["device_id"] == device_id]
            latest = _newest(scoped)

            last_run = session.scalar(select(PollRun).order_by(desc(PollRun.started_at)).limit(1))
            last_ok = session.scalar(
                select(PollRun)
                .where(PollRun.status.in_(("ok", "no_location")))
                .order_by(desc(PollRun.started_at))
                .limit(1)
            )

            interval = settings.effective_poll_interval_minutes
            return {
                "devices": per_device,
                "tracked_count": len(tracked),
                "requests_per_hour": round(len(tracked) * 60 / interval, 1) if interval else None,
                "default_device_id": default.device_id if default else None,
                "scope_device_id": device_id,
                "latest_observation": latest,
                "last_poll": _serialize_run(last_run, zone),
                "last_successful_poll": _serialize_run(last_ok, zone),
                "poller_running": _poller_appears_live(last_run, settings),
                "observations_today": sum(d["observations_today"] for d in scoped),
                "observations_total": sum(d["observations_total"] for d in scoped),
                "poll_interval_minutes": interval,
                "timezone": str(zone),
                "server_time": now.astimezone(zone).isoformat(),
                "notice": FIND_HUB_NOTICE,
            }

    # --------------------------------------------------------- timeline
    @app.get("/api/timeline")
    def timeline(
        day: str | None = Query(default=None, description="YYYY-MM-DD, local date"),
        device_id: str | None = Query(default=None, description="Omit for every device"),
        movement_threshold_meters: float | None = Query(default=None, ge=0),
        gap_threshold_minutes: float | None = Query(default=None, ge=0),
        timezone: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """One day of history, as one INDEPENDENT track per device.

        Tracks are never merged: distance and elapsed time between consecutive
        points are only meaningful within a single tracker.
        """
        zone = tz(timezone)
        target = _parse_day(day) or datetime.now(zone).date()
        with session_scope() as session:
            tracks = multi_day_timeline(
                session,
                [device_id] if device_id else None,
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
            names = {d.device_id: d.name for d in session.scalars(select(Device))}

        payload = [t.to_dict() for t in tracks]
        for track in payload:
            track["device_name"] = names.get(track["device_id"]) or track["device_name"]

        return {
            "day": target.isoformat(),
            "timezone": str(zone),
            "device_id": device_id,
            "movement_threshold_meters": (
                settings.movement_threshold_meters
                if movement_threshold_meters is None
                else movement_threshold_meters
            ),
            "gap_threshold_minutes": (
                settings.gap_threshold_minutes
                if gap_threshold_minutes is None
                else gap_threshold_minutes
            ),
            "path_disclaimer": "Observed path — actual route between detections may differ.",
            "tracks": payload,
            "total_observations": sum(len(t["points"]) for t in payload),
        }

    @app.get("/api/days")
    def days(
        device_id: str | None = Query(default=None), timezone: str | None = Query(default=None)
    ) -> dict[str, Any]:
        """Local dates holding data. Omit `device_id` for every device."""
        zone = tz(timezone)
        with session_scope() as session:
            return {"days": days_with_data(session, device_id, zone), "timezone": str(zone)}

    @app.get("/api/latest")
    def latest(
        device_id: str | None = Query(default=None),
        timezone: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Newest stored observation. Reads local history; does not query Google."""
        zone = tz(timezone)
        now = datetime.now(UTC)
        with session_scope() as session:
            stmt = select(LocationObservation)
            if device_id:
                stmt = stmt.where(LocationObservation.device_id == device_id)
            obs = session.scalar(stmt.order_by(desc(LocationObservation.observed_at)).limit(1))
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

        cycle = poll_once()
        return {
            "status": "ok" if cycle.ok else "error",
            "devices_polled": len(cycle.outcomes),
            "observations_returned": cycle.received,
            "observations_new": cycle.inserted,
            "duplicates": cycle.duplicates,
            "results": [
                {
                    "device_id": o.device_id,
                    "device_name": o.device_name,
                    "status": o.status,
                    "observations_new": o.inserted,
                    "duplicates": o.duplicates,
                    "error": o.error_message,
                }
                for o in cycle.outcomes
            ],
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
            start_utc, end_utc, label = _resolve_range(day, start, end, zone)
            rows = fetch_observations(session, device_id, start_utc, end_utc)
            name = "Bike history"
            if device_id:
                device = session.get(Device, device_id)
                if device:
                    name = device.name
                    label = f"{device.name.replace(' ', '-')}-{label}"
            body = export(fmt, rows, zone, name=f"{name} {label}")
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

    @app.post("/api/history/clear")
    def clear_history(
        confirm: bool = Body(default=False, embed=True),
        device_id: str | None = Body(default=None, embed=True),
    ) -> dict[str, Any]:
        """Delete ALL history, optionally for one device.

        Dry run unless `confirm=true`. History is never deleted silently.
        """
        with session_scope() as session:
            stmt = select(func.count(LocationObservation.id))
            if device_id:
                stmt = stmt.where(LocationObservation.device_id == device_id)
            doomed = int(session.scalar(stmt) or 0)

            if not confirm:
                return {
                    "deleted": 0,
                    "would_delete": doomed,
                    "device_id": device_id,
                    "message": "Dry run. Re-send with confirm=true to delete.",
                }

            query = session.query(LocationObservation)
            if device_id:
                query = query.filter(LocationObservation.device_id == device_id)
            query.delete(synchronize_session=False)
            log.warning("history_cleared", device_id=device_id, count=doomed)
            return {
                "deleted": doomed,
                "device_id": device_id,
                "message": f"Deleted {doomed} observation(s).",
            }

    # ------------------------------------------------------------- UI
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


# ------------------------------------------------------------ helpers
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


app = create_app()

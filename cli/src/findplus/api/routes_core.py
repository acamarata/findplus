"""Core routes: health, config, status, and the dashboard shell.

Purpose    : Meta endpoints the UI polls on load and the "/" shell page.
Inputs     : Request query params (device_id, timezone); app-level settings.
Outputs    : JSON meta payloads; the dashboard's index.html.
Constraints: Reading these never queries Google.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from sqlalchemy import desc, select

from findplus import __version__
from findplus.db.migrate import current_revision, is_up_to_date
from findplus.db.models import Device, PollRun
from findplus.db.session import session_scope
from findplus.findhub.bootstrap import describe_stored_auth
from findplus.state import get_default_device, get_tracked_devices
from findplus.timeline import local_zone

from ._helpers import _device_summary, _newest, _poller_appears_live, _serialize_run


def build_router(*, settings, static_dir: Path, find_hub_notice: str) -> APIRouter:
    router = APIRouter()

    def tz(name: str | None = None):
        return local_zone(name)

    @router.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "app": "findplus",
            "version": __version__,
            "pid": os.getpid(),
            "schema_revision": current_revision(),
            "schema_up_to_date": is_up_to_date(),
            "timezone": str(tz()),
            "notice": find_hub_notice,
        }

    @router.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "poll_interval_minutes": settings.effective_poll_interval_minutes,
            "movement_threshold_meters": settings.movement_threshold_meters,
            "gap_threshold_minutes": settings.gap_threshold_minutes,
            "retention_days": settings.retention_days,
            "ui_refresh_seconds": settings.ui_refresh_seconds,
            "timezone": str(tz()),
            "notice": find_hub_notice,
            "auth": describe_stored_auth(),
        }

    @router.get("/api/status")
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
                "notice": find_hub_notice,
            }

    if static_dir.is_dir():

        @router.get("/")
        def index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    return router

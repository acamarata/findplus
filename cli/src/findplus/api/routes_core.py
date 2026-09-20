"""Core routes: health, config, status, and the dashboard shell.

Purpose    : Meta endpoints the UI polls on load and the "/" shell page.
Inputs     : Request query params (device_id, timezone); app-level settings.
Outputs    : JSON meta payloads; the dashboard's index.html.
Constraints: Reading these never queries Google.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select

from findplus import __version__, honesty
from findplus.db.migrate import current_revision, is_up_to_date
from findplus.db.models import Device, PollRun
from findplus.db.session import session_scope
from findplus.providers.google_findhub.bootstrap import describe_stored_auth
from findplus.state import get_default_device, get_tracked_devices
from findplus.timeline import local_zone
from findplus.web_compose import compose_index

from ._helpers import (
    WIDGET_STALE_AFTER_MINUTES,
    _alerts_configured,
    _consecutive_failures,
    _device_summary,
    _group_rows,
    _iso_z,
    _newest,
    _poller_appears_live,
    _provider_health,
    _serialize_run,
    _widget_devices,
    _widget_show_map,
    _widget_state,
)


def _last_runs(session) -> tuple[Any, Any]:
    """`(newest PollRun, newest successful PollRun)` — either may be None."""
    last_run = session.scalar(select(PollRun).order_by(desc(PollRun.started_at)).limit(1))
    last_ok = session.scalar(
        select(PollRun)
        .where(PollRun.status.in_(("ok", "no_location")))
        .order_by(desc(PollRun.started_at))
        .limit(1)
    )
    return last_run, last_ok


def _status_extras(session, settings, last_run, next_poll_at) -> dict[str, Any]:
    """The seven fields api-contract.md § /api/status adds in P1.

    Split out of the handler so `status()` stays inside the 50-line rule; the
    values are computed from exactly the sources the rest of the handler uses.
    """
    return {
        "provider_health": _provider_health(),
        "alerts_configured": _alerts_configured(settings),
        "last_error_type": last_run.error_type if last_run else None,
        "consecutive_failures": _consecutive_failures(session),
        "last_poll_at": _iso_z(last_run.started_at) if last_run else None,
        "next_poll_at": _iso_z(next_poll_at),
    }


def build_router(*, settings, static_dir: Path, find_hub_notice: str) -> APIRouter:
    router = APIRouter(tags=["core"])

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
            # All six honesty.md sentences (E8 W5): find_hub, apple, alerts_latency,
            # presence_stale, lock_not_encryption, not_affiliated.
            "notices": honesty.NOTICES,
            "auth": describe_stored_auth(),
        }

    @router.get("/api/version")
    def version() -> dict[str, Any]:
        """Public: feeds the lock sweep and `findplus version --check`."""
        apple_installed = importlib.util.find_spec("findmy") is not None
        return {
            "version": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "providers": ["google-find-hub"] + (["apple-find-my"] if apple_installed else []),
            "apple_extra_installed": apple_installed,
        }

    @router.get("/api/icons")
    def icons() -> list[dict[str, str]]:
        """The pinned Lucide subset, for the CLI and test tooling.

        The dashboard's icon picker does not read this: it enumerates the
        `<symbol id="lucide-*">` elements already in the sprite, so the browser
        fetches icon artwork and grouping in one request.
        """
        from findplus import labels

        return labels.lucide_subset()

    @router.get("/api/widget")
    def widget() -> dict[str, Any]:
        """Compact, lock-aware feed for the Tauri menu-bar widget (E16)."""
        now = datetime.now(UTC)
        interval_seconds = settings.effective_poll_interval_minutes * 60
        with session_scope() as session:
            last_run = session.scalar(select(PollRun).order_by(desc(PollRun.started_at)).limit(1))
            last_poll_at = last_run.started_at if last_run else None
            next_poll_at = (
                last_poll_at + timedelta(seconds=interval_seconds) if last_poll_at else None
            )
            state = _widget_state(
                last_run.error_type if last_run else None,
                _consecutive_failures(session),
                last_poll_at,
                interval_seconds,
            )
            return {
                "state": state,
                "version": __version__,
                "last_poll_at": _iso_z(last_poll_at),
                "next_poll_at": _iso_z(next_poll_at),
                "tracked_count": len(get_tracked_devices(session)),
                "stale_after_minutes": WIDGET_STALE_AFTER_MINUTES,
                "devices": _widget_devices(session, now, WIDGET_STALE_AFTER_MINUTES),
                "groups": _group_rows(session),
                "show_map": _widget_show_map(session, settings),
                # The exact honesty.md sentence, not a paraphrase of it.
                "notice": honesty.ALERTS_LATENCY,
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

            last_run, last_ok = _last_runs(session)
            interval = settings.effective_poll_interval_minutes
            next_poll_at = last_run.started_at + timedelta(minutes=interval) if last_run else None
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
                **_status_extras(session, settings, last_run, next_poll_at),
            }

    if static_dir.is_dir():
        # Composed once at startup, not per request: the partials never change
        # while the process runs, and a missing one must fail here rather than
        # halfway through serving a dashboard (web_compose.compose_index raises).
        composed_index = compose_index(static_dir)

        @router.get("/", response_class=HTMLResponse)
        def index() -> HTMLResponse:
            return HTMLResponse(composed_index)

    return router

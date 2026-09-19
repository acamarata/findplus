"""History routes: timeline, days, latest, poll runs/now, export, retention.

Purpose    : Read and export stored location history; trigger a manual poll.
Inputs     : day/device/timezone filters, export format, delete confirmation.
Outputs    : Timeline tracks, export files, deletion counts.
Constraints: `poll-now` is the only route here that queries Google; it is
             POST-only and rate-limited via the injected `check_poll_cooldown`
             (process-wide state lives in api/__init__.py, matching the
             pre-split module-level cooldown state's semantics).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import desc, func, select

from findplus.db.models import Device, Group, LocationObservation, PollRun
from findplus.db.session import session_scope
from findplus.exporters import MEDIA_TYPES, export
from findplus.groups.repo import list_group_timeline
from findplus.logging_setup import get_logger
from findplus.timeline import (
    day_bounds_utc,
    days_with_data,
    fetch_observations,
    local_zone,
    multi_day_timeline,
)

from ._helpers import _parse_day, _resolve_range, _serialize_latest, _serialize_run

log = get_logger(__name__)


def build_router(*, settings, check_poll_cooldown) -> APIRouter:
    router = APIRouter(prefix="/api")

    def tz(name: str | None = None):
        return local_zone(name)

    @router.get("/timeline")
    def timeline(
        day: str | None = Query(default=None, description="YYYY-MM-DD, local date"),
        device_id: str | None = Query(default=None, description="Omit for every device"),
        group_id: int | None = Query(default=None, description="Per-member tracks for a group"),
        movement_threshold_meters: float | None = Query(default=None, ge=0),
        gap_threshold_minutes: float | None = Query(default=None, ge=0),
        timezone: str | None = Query(default=None),
    ) -> Any:
        """One day of history, as one INDEPENDENT track per device.

        Tracks are never merged: distance and elapsed time between consecutive
        points are only meaningful within a single tracker (PROMPT.md §2
        invariant 5). `group_id` returns a plain list of one dict per member
        device instead of the single-device dict shape below — never a
        cross-device-merged list.
        """
        zone = tz(timezone)
        target = _parse_day(day) or datetime.now(zone).date()

        if group_id is not None:
            return _group_timeline(group_id, target, zone)

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

    def _group_timeline(group_id: int, target, zone) -> list[dict[str, Any]]:
        """One dict per group member, each holding only that device's points.

        Never returns a single merged list — one entry in the result carries
        exactly one device_id's observations (invariant 5). The DB access
        lives in groups.repo so it is not duplicated between here and
        routes_groups.py / cli/groups.py.
        """
        start_utc, end_utc = day_bounds_utc(target, zone)
        with session_scope() as session:
            if session.get(Group, group_id) is None:
                raise HTTPException(status_code=404, detail=f"group {group_id} not found")
            return list_group_timeline(session, group_id, start_utc, end_utc)

    @router.get("/days")
    def days(
        device_id: str | None = Query(default=None), timezone: str | None = Query(default=None)
    ) -> dict[str, Any]:
        """Local dates holding data. Omit `device_id` for every device."""
        zone = tz(timezone)
        with session_scope() as session:
            return {"days": days_with_data(session, device_id, zone), "timezone": str(zone)}

    @router.get("/latest")
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

    @router.get("/poll-runs")
    def poll_runs(limit: int = Query(default=25, ge=1, le=200)) -> dict[str, Any]:
        zone = tz()
        with session_scope() as session:
            rows = list(
                session.scalars(select(PollRun).order_by(desc(PollRun.started_at)).limit(limit))
            )
            return {"runs": [_serialize_run(r, zone) for r in rows]}

    @router.post("/poll-now")
    def poll_now() -> dict[str, Any]:
        """Trigger one immediate Find Hub query. Rate-limited to protect the account."""
        wait = check_poll_cooldown()
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Manual polls are limited to one per minute. Try again in {wait:.0f}s.",
            )

        from findplus.poller import poll_once

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

    @router.get("/export")
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
        filename = f"findplus-{label}.{fmt}"
        return PlainTextResponse(
            content=body,
            media_type=MEDIA_TYPES[fmt],
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post("/history/delete-before")
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

    @router.post("/history/clear")
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

    return router

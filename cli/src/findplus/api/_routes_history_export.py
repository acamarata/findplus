"""Export and deletion routes split out of routes_history.py (file-cap split).

Purpose    : Export history (single-device or per-group-member) to a file,
             and the two destructive-but-confirmed history deletion routes.
Inputs     : format/day/range/device/group filters, delete confirmation.
Outputs    : Downloadable export bodies, deletion counts.
Constraints: Pulled out of routes_history.py when it grew past the PRI
             rule-7 300-line file cap. Mounted by api/__init__.py as its own
             sibling router (`app.include_router(build_export_router())`),
             exactly like every other routes_*.build_router() — never
             nested inside another `/api`-prefixed router (see
             routes_history.py's module docstring for why). Route paths and
             behaviour are unchanged from before the split.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import func, select

from findplus.db.models import Device, LocationObservation
from findplus.db.session import session_scope
from findplus.exporters import MEDIA_TYPES, export
from findplus.group_export import GroupNotFoundError, export_group
from findplus.logging_setup import get_logger
from findplus.timeline import day_bounds_utc, fetch_observations, local_zone

from ._helpers import _resolve_range
from .downloads import content_disposition

log = get_logger(__name__)


def _labels_for(session, rows) -> dict[str, str]:
    """device_id -> the user's label, for the devices in this export only.

    One query for the whole export, and none at all when there is nothing to
    label. Devices without a label are left out, so the exporters fall back to
    the denormalized provider name they already carry.
    """
    if not rows:
        return {}
    pairs = session.execute(
        select(Device.device_id, Device.label).where(
            Device.device_id.in_({r.device_id for r in rows})
        )
    ).all()
    return {device_id: label for device_id, label in pairs if label}


def build_export_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["history"])

    def _download(body: str, fmt: str, filename: str):
        from fastapi.responses import PlainTextResponse

        headers = {"Content-Disposition": content_disposition(filename)}
        return PlainTextResponse(content=body, media_type=MEDIA_TYPES[fmt], headers=headers)

    def _export_group(group_id: str, fmt: str, day, start, end, zone):
        """One track per member, never merged (`group_id` is `str`: see group_export.py)."""
        start_utc, end_utc, label = _resolve_range(day, start, end, zone)
        with session_scope() as session:
            try:
                body, name_slug = export_group(session, group_id, fmt, start_utc, end_utc, zone)
            except GroupNotFoundError as exc:
                raise HTTPException(status_code=404, detail="group not found") from exc
        return _download(body, fmt, f"findplus-group-{name_slug}-{label}.{fmt}")

    @router.get("/export")
    def export_history(
        fmt: str = Query(default="csv", pattern="^(csv|json|gpx|kml)$"),
        day: str | None = Query(default=None),
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        device_id: str | None = Query(default=None),
        group_id: str | None = Query(default=None, description="One track per member"),
        timezone: str | None = Query(default=None),
    ):
        zone = local_zone(timezone)
        if group_id is not None:
            return _export_group(group_id, fmt, day, start, end, zone)

        with session_scope() as session:
            start_utc, end_utc, label = _resolve_range(day, start, end, zone)
            rows = fetch_observations(session, device_id, start_utc, end_utc)
            name = "Find+ history"
            if device_id:
                device = session.get(Device, device_id)
                if device:
                    name = device.name
                    label = f"{device.name.replace(' ', '-')}-{label}"
            body = export(
                fmt, rows, zone, name=f"{name} {label}", labels=_labels_for(session, rows)
            )
        return _download(body, fmt, f"findplus-{label}.{fmt}")

    @router.post("/history/delete-before")
    def delete_before(
        before: str = Body(..., embed=True, description="YYYY-MM-DD, local date"),
        confirm: bool = Body(default=False, embed=True),
    ) -> dict[str, Any]:
        """Delete observations older than a date. Requires explicit confirmation."""
        from ._helpers import _parse_day

        zone = local_zone()
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

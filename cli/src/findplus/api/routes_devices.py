"""Device routes: list, refresh from Find Hub, set tracked set, set default.

Purpose    : Manage which devices are tracked and which one the UI focuses on.
Inputs     : device_ids, all_devices flag, a single device_id.
Outputs    : Device summaries and tracking state.
Constraints: `refresh` is the only route here that queries Google.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import func, select

from findplus.db.models import Device, LocationObservation
from findplus.db.session import session_scope
from findplus.state import (
    get_default_device,
    get_tracked_devices,
    set_default_device,
    track_all,
    track_devices,
    untrack_devices,
)


def build_router(*, settings) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/devices")
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
                        "provider": d.provider,
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

    @router.post("/devices/refresh")
    def refresh_devices() -> dict[str, Any]:
        """Re-query Find Hub for the account's device list."""
        from findplus.findhub.client import FindHubClient
        from findplus.ingest import upsert_device

        try:
            found = FindHubClient(settings).list_devices()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        with session_scope() as session:
            for d in found:
                upsert_device(session, d.device_id, d.name)
        return {"found": len(found)}

    @router.post("/devices/track")
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

    @router.post("/devices/default")
    def choose_default(device_id: str | None = Body(default=None, embed=True)) -> dict[str, Any]:
        """Set which device the dashboard focuses on first."""
        with session_scope() as session:
            set_default_device(session, device_id)
            return {"default_device_id": device_id}

    return router

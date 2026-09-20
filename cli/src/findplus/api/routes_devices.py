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

from findplus.db.models import Device, DeviceGroup, LocationObservation
from findplus.db.session import session_scope
from findplus.redaction import redact_text
from findplus.state import (
    get_default_device,
    get_tracked_devices,
    set_default_device,
    track_all,
    track_devices,
    untrack_devices,
)


def _query_every_provider() -> tuple[list[tuple[str, Any]], list[str], dict[str, str]]:
    """Ask every installed, signed-in provider for its device list.

    Returns (rows, queried, errors). A provider that is not installed or not
    signed in is skipped rather than reported: the common case is exactly one
    configured. One provider's outage never hides another's results.
    """
    from findplus.providers.base import available_providers, get_provider

    rows: list[tuple[str, Any]] = []
    queried: list[str] = []
    errors: dict[str, str] = {}
    for name in available_providers():
        try:
            provider = get_provider(name)
            if not provider.is_available()[0] or not provider.is_authenticated():
                continue
            queried.append(name)
            rows.extend((name, d) for d in provider.list_devices())
        except Exception as exc:  # one provider's outage is not the others'
            errors[name] = redact_text(str(exc)[:200]) or "failed"
    return rows, queried, errors


def _refresh_from_providers() -> tuple[list[tuple[str, Any]], list[str], dict[str, str]]:
    """_query_every_provider, with the two failures the user needs words for."""
    rows, queried, errors = _query_every_provider()
    if not queried:
        raise HTTPException(
            status_code=409, detail="No provider is signed in. Run `findplus auth` first."
        )
    if errors and not rows:
        # Every provider that was asked failed: name them in words the user can
        # act on, instead of surfacing a raw exception message verbatim.
        names = ", ".join(sorted(errors))
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach {names}. Check your connection and sign-in, then retry.",
        )
    return rows, queried, errors


def build_router(*, settings) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["devices"])

    def _groups_by_device(session) -> dict[str, list[int]]:
        """device_id -> the group ids it belongs to. One query, not one per device."""
        out: dict[str, list[int]] = {}
        for device_id, group_id in session.execute(
            select(DeviceGroup.device_id, DeviceGroup.group_id)
        ).all():
            out.setdefault(device_id, []).append(group_id)
        return out

    def _presence_by_device(session) -> dict[str, list[dict[str, Any]]]:
        """device_id -> the places it is currently inside, per api-contract.md."""
        from findplus.places.repo import current_presence

        out: dict[str, list[dict[str, Any]]] = {}
        for row in current_presence(session):
            if row["state"] != "inside":
                continue
            since = row["since_observed_at"]
            out.setdefault(row["device_id"], []).append(
                {
                    "place_id": row["place_id"],
                    "place_name": row["place_name"],
                    "since": since.isoformat() if since else None,
                }
            )
        return out

    @router.get("/devices")
    def devices() -> dict[str, Any]:
        with session_scope() as session:
            rows = list(session.scalars(select(Device).order_by(Device.name)))
            default = get_default_device(session)
            groups_by_device = _groups_by_device(session)
            presence_by_device = _presence_by_device(session)
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
                        # api-contract.md § /api/devices pins both keys; they were
                        # never emitted, so every consumer had to call
                        # /api/groups and /api/places/presence itself (E1 CR-C).
                        "groups": groups_by_device.get(d.device_id, []),
                        "presence": presence_by_device.get(d.device_id, []),
                    }
                    for d in rows
                ],
            }

    @router.post("/devices/refresh")
    def refresh_devices() -> dict[str, Any]:
        """Re-query every authenticated provider for its device list.

        The button says "Refresh from your providers", plural, but this
        constructed FindHubClient directly: an accessory added with
        `findplus apple add-accessory` never appeared from the dashboard, and
        nothing on screen said Apple was CLI-only (E1 honesty round 2 F4).
        A provider that is not installed or not signed in is skipped, not an
        error -- the common case is exactly one provider configured.
        """
        from findplus.ingest import upsert_device

        found, queried, errors = _refresh_from_providers()

        with session_scope() as session:
            for provider_name, d in found:
                upsert_device(session, d.device_id, d.name, provider=provider_name)
        return {"found": len(found), "providers": queried, "errors": errors}

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

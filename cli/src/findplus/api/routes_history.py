"""History routes: timeline, days, latest, poll runs/now.

Purpose    : Read stored location history; trigger a manual poll. Export and
             the two destructive-but-confirmed deletion routes live in
             `_routes_history_export.py` (split out at the PRI rule-7
             300-line file cap) and are mounted as their own sibling router
             by api/__init__.py, same as every other routes_*.build_router()
             — nesting an `/api`-prefixed router inside this one via
             `include_router()` silently double-prefixes it to
             `/api/api/...` (empirically confirmed against FastAPI 0.141's
             routing, and a second level of nesting 404s even once the
             prefix is fixed, so this module never nests routers either).
Inputs     : day/device/timezone filters.
Outputs    : Timeline tracks, poll-run summaries.
Constraints: `poll-now` is the only route here that queries Google; POST-only,
             rate-limited via the injected `check_poll_cooldown` (process-wide
             state lives in api/__init__.py). Handlers that close over a
             factory collaborator sit in small register-functions; the rest
             are module-level (E13 loop-1 function-cap refactor; routes and
             signatures unchanged).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from findplus.db.models import Device, Group, LocationObservation, PollRun
from findplus.db.session import session_scope
from findplus.groups.repo import list_group_timeline
from findplus.logging_setup import get_logger
from findplus.timeline import day_bounds_utc, days_with_data, local_zone, multi_day_timeline

from ._helpers import _parse_day, _serialize_latest, _serialize_run

log = get_logger(__name__)


def _tz(name: str | None = None):
    """Every handler in this module resolves timezones through one helper."""
    return local_zone(name)


def _resolved_thresholds(
    settings, movement_threshold_meters: float | None, gap_threshold_minutes: float | None
) -> tuple[float, float]:
    """(movement, gap) with the settings fallback applied to omitted params.

    Computed once and returned because the timeline route needs each value
    twice: passed into multi_day_timeline() and echoed back in the payload.
    """
    return (
        settings.movement_threshold_meters
        if movement_threshold_meters is None
        else movement_threshold_meters,
        settings.gap_threshold_minutes if gap_threshold_minutes is None else gap_threshold_minutes,
    )


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


def _named_payload(tracks, names: dict[str, str]) -> list[dict[str, Any]]:
    """Track dicts with device_name overlaid from the devices table.

    A track's own device_name is whatever the provider last reported; the
    devices table is the authoritative label the user edits.
    """
    payload = [t.to_dict() for t in tracks]
    for track in payload:
        track["device_name"] = names.get(track["device_id"]) or track["device_name"]
    return payload


def _register_timeline_route(router: APIRouter, *, settings) -> None:
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
        zone = _tz(timezone)
        target = _parse_day(day) or datetime.now(zone).date()

        if group_id is not None:
            return _group_timeline(group_id, target, zone)

        movement, gap = _resolved_thresholds(
            settings, movement_threshold_meters, gap_threshold_minutes
        )
        with session_scope() as session:
            tracks = multi_day_timeline(
                session,
                [device_id] if device_id else None,
                target,
                tz=zone,
                movement_threshold_meters=movement,
                gap_threshold_minutes=gap,
            )
            names = {d.device_id: d.name for d in session.scalars(select(Device))}

        payload = _named_payload(tracks, names)

        return {
            "day": target.isoformat(),
            "timezone": str(zone),
            "device_id": device_id,
            "movement_threshold_meters": movement,
            "gap_threshold_minutes": gap,
            "path_disclaimer": "Observed path — actual route between detections may differ.",
            "tracks": payload,
            "total_observations": sum(len(t["points"]) for t in payload),
        }


def days(
    device_id: str | None = Query(default=None), timezone: str | None = Query(default=None)
) -> dict[str, Any]:
    """Local dates holding data. Omit `device_id` for every device."""
    zone = _tz(timezone)
    with session_scope() as session:
        return {"days": days_with_data(session, device_id, zone), "timezone": str(zone)}


def latest(
    device_id: str | None = Query(default=None),
    timezone: str | None = Query(default=None),
) -> dict[str, Any]:
    """Newest stored observation. Reads local history; does not query Google."""
    zone = _tz(timezone)
    now = datetime.now(UTC)
    with session_scope() as session:
        stmt = select(LocationObservation)
        if device_id:
            stmt = stmt.where(LocationObservation.device_id == device_id)
        obs = session.scalar(stmt.order_by(desc(LocationObservation.observed_at)).limit(1))
        if obs is None:
            raise HTTPException(status_code=404, detail="No observations recorded yet.")
        return _serialize_latest(obs, zone, now) or {}


def poll_runs(limit: int = Query(default=25, ge=1, le=200)) -> dict[str, Any]:
    zone = _tz()
    with session_scope() as session:
        rows = list(
            session.scalars(select(PollRun).order_by(desc(PollRun.started_at)).limit(limit))
        )
        return {"runs": [_serialize_run(r, zone) for r in rows]}


def _register_poll_now_route(router: APIRouter, *, check_poll_cooldown) -> None:
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


def build_router(*, settings, check_poll_cooldown) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["history"])
    _register_timeline_route(router, settings=settings)
    router.add_api_route("/days", days, methods=["GET"])
    router.add_api_route("/latest", latest, methods=["GET"])
    router.add_api_route("/poll-runs", poll_runs, methods=["GET"])
    _register_poll_now_route(router, check_poll_cooldown=check_poll_cooldown)
    return router

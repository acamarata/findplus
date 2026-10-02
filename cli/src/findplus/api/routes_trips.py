"""Trips routes: stays, trips and gaps for one device, plus the optional road route.

Purpose    : `GET /api/trips` serves the segmentation the timeline view draws;
             `GET /api/trips/route` asks the user's own routing server for a
             likely road path for one trip (opt-in); `routing.endpoint` is the
             per-key setting that turns it on.
Inputs     : device_id, date (+days), trip_id, optional timezone.
Outputs    : See findplus.trips.service.trips_payload and findplus.trips.routing.
Constraints: One device per call, never merged. Locked apps 401 these like every
             other /api/ data route. `/trips/route` sends the trip's sightings
             to the configured server and ONLY then; with no endpoint set it
             makes no request. Reads local history only; never queries Google.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from findplus import honesty
from findplus.db.models import Device
from findplus.db.session import session_scope
from findplus.state import get_setting, set_setting
from findplus.timeline import local_zone
from findplus.trips.routing import SETTING_KEY, likely_route, normalize_endpoint
from findplus.trips.segment import SegmentParams
from findplus.trips.service import MAX_DAYS, segmentation_for, trips_for

from ._helpers import _parse_day


def _require_device(session, device_id: str) -> None:
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail=f"device {device_id!r} not found")


def trips(
    device_id: str = Query(..., description="One device; trips are never merged across devices"),
    date: str | None = Query(default=None, description="YYYY-MM-DD local date; default today"),
    days: int = Query(default=1, ge=1, le=MAX_DAYS, description="Number of local days from date"),
    gap_minutes: float | None = Query(default=None, ge=1, description="Gap marker threshold"),
    timezone: str | None = Query(default=None),
) -> dict[str, Any]:
    """Stays (with a saved-place label), trips between them, and no-sighting gaps.

    Repeated near-identical fixes collapse into one stay with a fix count,
    jitter inside the accuracy circle never creates a trip, and a single
    impossible-speed fix is left out and listed under `outliers`. Distances are
    approximate straight lines between sightings.
    """
    zone = local_zone(timezone)
    day = _parse_day(date) or datetime.now(zone).date()
    with session_scope() as session:
        _require_device(session, device_id)
        routing = bool(get_setting(session, SETTING_KEY))
        return trips_for(
            session, device_id, day, days, zone, gap_min=gap_minutes, routing_enabled=routing
        )


def trip_route(
    device_id: str = Query(...),
    trip_id: str = Query(..., description="The `id` of a trip from /api/trips"),
    date: str | None = Query(default=None, description="Same date used to list the trip"),
    days: int | None = Query(default=None, ge=1, le=MAX_DAYS),
    timezone: str | None = Query(default=None),
) -> dict[str, Any]:
    """A likely road route for one trip, or dashed straight segments.

    Contacts the routing server only when `routing.endpoint` is set; otherwise
    (or on any failure) the answer is the straight-line fallback.
    """
    zone = local_zone(timezone)
    start = _parse_day(date)
    window = days or 1
    if start is None:
        stamp = _stamp(trip_id)
        start = datetime.fromtimestamp(stamp, zone).date() - timedelta(days=1)
        window = 3
    with session_scope() as session:
        _require_device(session, device_id)
        endpoint = get_setting(session, SETTING_KEY)
        seg, _ = segmentation_for(session, device_id, start, window, zone, SegmentParams())
    trip = next((t for t in seg.trips if t.id == trip_id), None)
    if trip is None:
        raise HTTPException(status_code=404, detail=f"trip {trip_id!r} not found")
    result = likely_route(endpoint, list(trip.points))
    return {
        "trip_id": trip.id,
        "device_id": device_id,
        "routing_notice": honesty.ROUTING_PRIVACY,
        **result,
    }


def _stamp(trip_id: str) -> int:
    try:
        return int(trip_id.removeprefix("t"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"bad trip id {trip_id!r}") from exc


def get_routing_endpoint() -> dict[str, Any]:
    with session_scope() as session:
        return {SETTING_KEY: get_setting(session, SETTING_KEY) or ""}


def set_routing_endpoint(value: str | None = Body(default=None, embed=True)) -> dict[str, Any]:
    """Set (or clear, with an empty value) the OSRM-compatible routing server.

    While set, the sightings of any trip whose route you open are sent to that
    server. Empty means off, which is the default.
    """
    try:
        clean = normalize_endpoint(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with session_scope() as session:
        set_setting(session, SETTING_KEY, clean or None)
    return {SETTING_KEY: clean, "notice": honesty.ROUTING_PRIVACY}


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["history"])
    router.add_api_route("/trips", trips, methods=["GET"])
    router.add_api_route("/trips/route", trip_route, methods=["GET"])
    router.add_api_route(f"/settings/{SETTING_KEY}", get_routing_endpoint, methods=["GET"])
    router.add_api_route(f"/settings/{SETTING_KEY}", set_routing_endpoint, methods=["POST"])
    return router

"""Place routes: CRUD, event log, and current presence.

Purpose    : Let the dashboard manage saved places and read the geofence
             event log and live presence.
Outputs    : Place/event/presence dicts. ValueError from the repo layer maps
             to 409 (duplicate name), 404 (not found) or 422 (validation).
Constraints: Gated by SessionAuthMiddleware like every /api/ path not in
             _PUBLIC (routes_places is never in that set).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from findplus.db.models import Place, PlaceEvent
from findplus.db.session import session_scope
from findplus.places.repo import (
    create_place,
    current_presence,
    delete_place,
    list_place_events,
    list_places,
    update_place,
)


class PlaceCreate(BaseModel):
    name: str
    latitude: float
    longitude: float
    radius_meters: int
    color: str = "#2f80ed"
    enter_confirmations: int = 1
    exit_confirmations: int = 2


class PlaceUpdate(BaseModel):
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_meters: int | None = None
    color: str | None = None
    enter_confirmations: int | None = None
    exit_confirmations: int | None = None


def _place_to_dict(p: Place) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "latitude": p.latitude_e7 / 1e7,
        "longitude": p.longitude_e7 / 1e7,
        "radius_meters": p.radius_meters,
        "color": p.color,
        "enter_confirmations": p.enter_confirmations,
        "exit_confirmations": p.exit_confirmations,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
        "devices_inside": getattr(p, "_devices_inside", []),
    }


def _event_to_dict(e: PlaceEvent) -> dict[str, Any]:
    lag = int((e.fetched_at - e.observed_at).total_seconds() / 60)
    return {
        "id": e.id,
        "place_id": e.place_id,
        "place_name": getattr(e, "_place_name", ""),
        "device_id": e.device_id,
        "device_name": getattr(e, "_device_name", ""),
        "event_type": e.event_type,
        "observed_at": e.observed_at.isoformat(),
        "fetched_at": e.fetched_at.isoformat(),
        "lag_minutes": lag,
        "confidence": e.confidence,
        "distance_meters": e.distance_meters,
        "accuracy_meters": e.accuracy_meters,
        "notified_at": e.notified_at.isoformat() if e.notified_at else None,
    }


def _map_value_error(exc: ValueError) -> HTTPException:
    text = str(exc)
    if "not found" in text:
        return HTTPException(status_code=404, detail=text)
    code = 409 if "already exists" in text else 422
    return HTTPException(status_code=code, detail=text)


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/places", tags=["places"])

    @router.get("")
    def get_places() -> list[dict[str, Any]]:
        with session_scope() as s:
            return [_place_to_dict(p) for p in list_places(s)]

    @router.post("", status_code=201)
    def post_place(body: PlaceCreate) -> dict[str, Any]:
        with session_scope() as s:
            try:
                p = create_place(
                    s,
                    name=body.name,
                    latitude_e7=round(body.latitude * 1e7),
                    longitude_e7=round(body.longitude * 1e7),
                    radius_meters=body.radius_meters,
                    color=body.color,
                    enter_confirmations=body.enter_confirmations,
                    exit_confirmations=body.exit_confirmations,
                )
            except ValueError as exc:
                s.rollback()
                raise _map_value_error(exc) from exc
            s.commit()
            return _place_to_dict(p)

    @router.put("/{place_id}")
    def put_place(place_id: int, body: PlaceUpdate) -> dict[str, Any]:
        kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
        if "latitude" in kwargs:
            kwargs["latitude_e7"] = round(kwargs.pop("latitude") * 1e7)
        if "longitude" in kwargs:
            kwargs["longitude_e7"] = round(kwargs.pop("longitude") * 1e7)
        with session_scope() as s:
            try:
                p = update_place(s, place_id, **kwargs)
            except ValueError as exc:
                s.rollback()
                raise _map_value_error(exc) from exc
            s.commit()
            return _place_to_dict(p)

    @router.delete("/{place_id}", status_code=204)
    def del_place(place_id: int) -> Response:
        with session_scope() as s:
            try:
                delete_place(s, place_id)
            except ValueError as exc:
                s.rollback()
                raise _map_value_error(exc) from exc
            s.commit()
        return Response(status_code=204)

    @router.get("/events")
    def get_events(
        place_id: int | None = None,
        device_id: str | None = None,
        group_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with session_scope() as s:
            rows = list_place_events(
                s,
                place_id=place_id,
                device_id=device_id,
                group_id=group_id,
                since=since,
                until=until,
                limit=limit,
            )
            return [_event_to_dict(e) for e in rows]

    @router.get("/presence")
    def get_presence(device_id: str | None = None) -> list[dict[str, Any]]:
        with session_scope() as s:
            rows = current_presence(s, device_id=device_id)
            for r in rows:
                if r["since_observed_at"] is not None:
                    r["since_observed_at"] = r["since_observed_at"].isoformat()
            return rows

    return router

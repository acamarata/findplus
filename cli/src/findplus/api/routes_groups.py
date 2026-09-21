"""Group routes: CRUD, membership, presence, and the group event log.

Purpose    : Let the dashboard manage device groups and read live presence
             and quorum-gated crossing events.
Outputs    : Group/presence/event dicts. ValueError from the repo layer maps
             to 409 (duplicate name), 404 (not found) or 422 (validation);
             a duplicate-name IntegrityError on create maps to 409 directly.
Constraints: Gated by SessionAuthMiddleware like every /api/ path not in
             _PUBLIC (routes_groups is never in that set). The presence
             endpoint delegates to groups.repo.build_presence(), which
             delegates to the pure groups.presence.group_presence() engine
             — no presence logic is inlined here (invariant: PROMPT.md §2).
             Handlers close over nothing, so they are module-level functions
             and build_router only registers them (E13 loop-1 function-cap
             refactor; routes and signatures unchanged).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from findplus.config import get_settings
from findplus.db.models import Group
from findplus.db.session import session_scope
from findplus.groups.presence import MemberStatus, verdict_label
from findplus.groups.repo import (
    build_presence,
    create_group,
    delete_group,
    list_group_place_events,
    list_groups,
    set_members,
    update_group,
)


class GroupCreate(BaseModel):
    name: str
    color: str = "#27ae60"
    icon: str = "lucide:users"
    quorum: str = "majority"
    cluster_radius_meters: int = 150
    stale_after_minutes: int = 90
    member_ids: list[str] = []


class GroupUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    icon: str | None = None
    quorum: str | None = None
    cluster_radius_meters: int | None = None
    stale_after_minutes: int | None = None


class MembersBody(BaseModel):
    member_ids: list[str]


def _group_to_dict(g: Group) -> dict[str, Any]:
    return {
        "id": g.id,
        "name": g.name,
        "color": g.color,
        "icon": g.icon,
        "quorum": g.quorum,
        "cluster_radius_meters": g.cluster_radius_meters,
        "stale_after_minutes": g.stale_after_minutes,
        "members": getattr(g, "_members", []),
    }


def _status_to_dict(s: MemberStatus) -> dict[str, Any]:
    d = asdict(s)
    # UtcDateTime already returns aware UTC: isoformat() emits the offset. Appending
    # a "Z" on top of it produces "...+00:00Z", which no ISO parser accepts.
    d["last_observed_at"] = s.last_observed_at.isoformat() if s.last_observed_at else None
    return d


def _map_value_error(exc: ValueError) -> HTTPException:
    text = str(exc)
    if "not found" in text:
        return HTTPException(status_code=404, detail=text)
    code = 409 if "already exists" in text else 422
    return HTTPException(status_code=code, detail=text)


def get_groups() -> list[dict[str, Any]]:
    with session_scope() as s:
        return [_group_to_dict(g) for g in list_groups(s)]


def post_group(body: GroupCreate) -> dict[str, Any]:
    with session_scope() as s:
        try:
            g = create_group(
                s,
                name=body.name,
                color=body.color,
                icon=body.icon,
                quorum=body.quorum,
                cluster_radius_meters=body.cluster_radius_meters,
                stale_after_minutes=body.stale_after_minutes,
                member_ids=body.member_ids,
            )
        except ValueError as exc:
            s.rollback()
            raise _map_value_error(exc) from exc
        except IntegrityError as exc:
            s.rollback()
            if "UNIQUE" not in str(exc):
                raise
            raise HTTPException(
                status_code=409, detail=f"group name {body.name!r} already exists"
            ) from exc
        s.commit()
        return _group_to_dict(g)


def put_group(group_id: int, body: GroupUpdate) -> dict[str, Any]:
    with session_scope() as s:
        try:
            g = update_group(s, group_id, **body.model_dump())
        except ValueError as exc:
            s.rollback()
            raise _map_value_error(exc) from exc
        except IntegrityError as exc:
            # update_group() never checks the name against the others, so a
            # rename onto an existing one reaches the UNIQUE index and used
            # to leave the route as a 500. Same 409 as create: the group
            # dialog reads "already exists" and focuses the name field
            # (specs/groups-ui.md § Error mapping).
            s.rollback()
            if "UNIQUE" not in str(exc):
                raise
            raise HTTPException(
                status_code=409, detail=f"group {body.name!r} already exists"
            ) from exc
        s.commit()
        return _group_to_dict(g)


def del_group(group_id: int) -> Response:
    with session_scope() as s:
        try:
            delete_group(s, group_id)
        except ValueError as exc:
            s.rollback()
            raise _map_value_error(exc) from exc
        s.commit()
    return Response(status_code=204)


def put_members(group_id: int, body: MembersBody) -> dict[str, Any]:
    with session_scope() as s:
        try:
            g = set_members(s, group_id, body.member_ids)
        except ValueError as exc:
            s.rollback()
            raise _map_value_error(exc) from exc
        s.commit()
        return _group_to_dict(g)


def get_events(
    group_id: int | None = None,
    place_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with session_scope() as s:
        if group_id is not None and s.get(Group, group_id) is None:
            raise HTTPException(status_code=404, detail=f"group {group_id} not found")
        rows = list_group_place_events(
            s, group_id=group_id, place_id=place_id, since=since, until=until, limit=limit
        )
        for r in rows:
            r["observed_at"] = r["observed_at"].isoformat()
            r["notified_at"] = r["notified_at"].isoformat() if r["notified_at"] else None
        return rows


def get_presence(group_id: int, window: int = Query(default=60)) -> dict[str, Any]:
    with session_scope() as s:
        group = s.get(Group, group_id)
        if group is None:
            raise HTTPException(status_code=404, detail=f"group {group_id} not found")
        movement_threshold_meters = get_settings().movement_threshold_meters
        presence, statuses = build_presence(s, group, window, movement_threshold_meters)
        body = asdict(presence)
        # One phrase, computed once, so the dashboard, the widget and the
        # CLI cannot drift apart again (E1 honesty round 3 F3/F4).
        body["verdict_label"] = verdict_label(
            presence.verdict,
            diverged=presence.diverged,
            reporting_count=presence.reporting_count,
            considered_count=presence.considered_count,
        )
        body["members"] = [_status_to_dict(s2) for s2 in statuses]
        return body


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/groups", tags=["groups"])
    router.add_api_route("", get_groups, methods=["GET"])
    router.add_api_route("", post_group, methods=["POST"], status_code=201)
    router.add_api_route("/{group_id}", put_group, methods=["PUT"])
    router.add_api_route("/{group_id}", del_group, methods=["DELETE"], status_code=204)
    router.add_api_route("/{group_id}/members", put_members, methods=["PUT"])
    router.add_api_route("/events", get_events, methods=["GET"])
    router.add_api_route("/{group_id}/presence", get_presence, methods=["GET"])
    return router

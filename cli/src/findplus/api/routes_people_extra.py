"""People routes with literal paths: suggestions, tracker roles, left-behind, settings.

Purpose    : GET /api/people/suggestions is a pure preview (spec § 2); POST
             /api/people/suggestions/accept applies the owner's edited choice.
             PUT /api/people/trackers/{device_id} sets a role or carry weight.
             Left-behind episodes can be listed and dismissed ("I know").
Outputs    : JSON dicts; errors through routes_people.map_value_error.
Constraints: Registered on the /api/people router BEFORE its /{group_id}
             routes. Gated by the lock middleware like every /api/ path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import or_, select

from findplus.alerts.dispatch_left_behind import LEFT_BEHIND_ALERTS
from findplus.db.models import Place
from findplus.db.models_people import LeftBehind
from findplus.db.session import session_scope
from findplus.device_labels import unique_names
from findplus.people import left_behind, replay, repo, suggestions
from findplus.state import get_setting, set_setting

from ._people_http import run_write as _run


class AcceptMember(BaseModel):
    device_id: str
    role: str | None = None


class AcceptItem(BaseModel):
    action: str = "create"
    name: str = ""
    kind: str = "person"
    group_id: int | None = None
    members: list[AcceptMember] = []


class AcceptBody(BaseModel):
    accept: list[AcceptItem] = []
    dismiss: list[str] = []


class TrackerBody(BaseModel):
    role: str | None = None
    carry_weight: float | None = None


class PeopleSettings(BaseModel):
    left_behind_alerts: bool | None = None


def get_suggestions() -> dict[str, Any]:
    with session_scope() as s:
        return suggestions.build(s)


def post_accept(body: AcceptBody) -> dict[str, Any]:
    items = [i.model_dump(exclude_unset=False) for i in body.accept]
    for item, raw in zip(items, body.accept, strict=True):
        item["members"] = [m.model_dump(exclude_unset=True) for m in raw.members]
    out = _run(lambda s: suggestions.accept(s, items, body.dismiss))
    if body.accept:
        replay.request("people")  # fill in past days for the new people (uat116 #4)
    return out


def get_replay() -> dict[str, Any]:
    """{state: idle|running|done|failed, done, total, failed}: "Updating past days..."."""
    return replay.status()


def put_tracker(device_id: str, body: TrackerBody) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)

    def update(s):
        d = repo.set_tracker(s, device_id, fields)
        return {"device_id": d.device_id, "role": d.role, "carry_weight": d.carry_weight}

    return _run(update)


def _episode(row: LeftBehind, names: dict[str, str], places: dict[int, str]) -> dict[str, Any]:
    def iso(v):
        return v.isoformat() if v else None

    return {
        "id": row.id,
        "person_id": row.group_id,
        "device_id": row.device_id,
        "device_name": names.get(row.device_id, row.device_id),
        "place_id": row.place_id,
        "place_name": places.get(row.place_id) if row.place_id else None,
        "latitude": row.anchor_lat_e7 / 1e7,
        "longitude": row.anchor_lon_e7 / 1e7,
        "state": row.state,
        "started_observed_at": iso(row.started_observed_at),
        "confirmed_at": iso(row.confirmed_at),
        "cleared_at": iso(row.cleared_at),
        "clear_reason": row.clear_reason,
        "notified_at": iso(row.notified_at),
    }


def get_left_behind(group_id: int) -> list[dict[str, Any]]:
    """Open episodes plus those cleared in the last 24 hours."""

    def read(s):
        repo.get_person(s, group_id)
        since = datetime.now(UTC) - timedelta(hours=24)
        rows = s.scalars(
            select(LeftBehind)
            .where(LeftBehind.group_id == group_id)
            .where(or_(LeftBehind.cleared_at.is_(None), LeftBehind.cleared_at >= since))
            .order_by(LeftBehind.started_observed_at.desc())
        ).all()
        places = dict(s.execute(select(Place.id, Place.name)).all())
        names = unique_names(s)
        return [_episode(r, names, places) for r in rows]

    return _run(read)


def post_dismiss(group_id: int, episode_id: int) -> dict[str, Any]:
    def dismiss(s):
        row = left_behind.dismiss(s, group_id, episode_id)
        places = dict(s.execute(select(Place.id, Place.name)).all())
        return _episode(row, unique_names(s), places)

    return _run(dismiss)


def _settings(s) -> dict[str, Any]:
    return {"left_behind_alerts": get_setting(s, LEFT_BEHIND_ALERTS, "1") != "0"}


def get_settings() -> dict[str, Any]:
    with session_scope() as s:
        return _settings(s)


def put_settings(body: PeopleSettings) -> dict[str, Any]:
    def write(s):
        if body.left_behind_alerts is not None:
            set_setting(s, LEFT_BEHIND_ALERTS, "1" if body.left_behind_alerts else "0")
        return _settings(s)

    return _run(write)


def register(router: APIRouter) -> None:
    router.add_api_route("/replay", get_replay, methods=["GET"])
    router.add_api_route("/suggestions", get_suggestions, methods=["GET"])
    router.add_api_route("/suggestions/accept", post_accept, methods=["POST"])
    router.add_api_route("/settings", get_settings, methods=["GET"])
    router.add_api_route("/settings", put_settings, methods=["PUT"])
    router.add_api_route("/trackers/{device_id}", put_tracker, methods=["PUT"])
    router.add_api_route("/{group_id}/left-behind", get_left_behind, methods=["GET"])
    router.add_api_route(
        "/{group_id}/left-behind/{episode_id}/dismiss", post_dismiss, methods=["POST"]
    )

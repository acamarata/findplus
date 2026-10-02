"""People routes: persons and pets, their trackers, and where they are now.

Purpose    : CRUD over people (groups with kind person/pet, specs/people-and-
             presence.md § 1.1) and GET /api/people/{id}/now (§ 3). The
             suggestion, tracker-role, left-behind and settings routes live in
             routes_people_extra.py and are registered first, so a literal path
             such as /api/people/suggestions never reaches /{group_id}.
Outputs    : people/repo.person_dict shapes. ValueError from the repo maps to
             404 (not found), 409 (already exists / already belongs to) or 422.
Constraints: Gated by SessionAuthMiddleware like every /api/ path not in
             _PUBLIC: every route here 401s while the app is locked.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from findplus.db.session import session_scope
from findplus.groups.repo import delete_group, set_members, update_group
from findplus.people import repo

from . import routes_people_extra
from ._people_http import map_value_error
from ._people_http import run_write as _run


class PersonCreate(BaseModel):
    name: str
    kind: str = "person"
    member_ids: list[str] = []
    #: device_id -> role (None = guess from the tracker's name).
    roles: dict[str, str | None] = {}
    color: str | None = None
    icon: str | None = None


class PersonUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    color: str | None = None
    icon: str | None = None
    cluster_radius_meters: int | None = None
    stale_after_minutes: int | None = None


class MembersBody(BaseModel):
    member_ids: list[str]


def get_people() -> list[dict[str, Any]]:
    with session_scope() as s:
        return [repo.person_dict(p) for p in repo.list_people(s)]


def post_person(body: PersonCreate) -> dict[str, Any]:
    def create(s):
        return repo.person_dict(
            repo.create_person(s, name=body.name, kind=body.kind, member_ids=body.member_ids,
                               roles=body.roles, color=body.color, icon=body.icon)
        )  # fmt: skip

    return _run(create)


def _person_view(s, group_id: int) -> dict[str, Any]:
    group = repo.get_person(s, group_id)
    group._trackers = repo.trackers_of(s, group_id, repo.unique_names(s))
    return repo.person_dict(group)


def get_person(group_id: int) -> dict[str, Any]:
    return _run(_person_view, group_id)


def patch_person(group_id: int, body: PersonUpdate) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    if fields.get("kind") not in (None, "person", "pet"):
        raise HTTPException(status_code=422, detail="kind must be person or pet")

    def update(s):
        repo.get_person(s, group_id)
        update_group(s, group_id, **fields)
        return _person_view(s, group_id)

    return _run(update)


def put_members(group_id: int, body: MembersBody) -> dict[str, Any]:
    def replace(s):
        repo.get_person(s, group_id)
        set_members(s, group_id, body.member_ids)
        return _person_view(s, group_id)

    return _run(replace)


def del_person(group_id: int) -> Response:
    def delete(s):
        repo.get_person(s, group_id)
        delete_group(s, group_id)

    _run(delete)
    return Response(status_code=204)


def get_now(group_id: int) -> dict[str, Any]:
    with session_scope() as s:
        try:
            group = repo.get_person(s, group_id)
        except ValueError as exc:
            raise map_value_error(exc) from exc
        return {"person": {"id": group.id, "name": group.name}, **repo.now_dict(s, group)}


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/people", tags=["people"])
    routes_people_extra.register(router)
    router.add_api_route("", get_people, methods=["GET"])
    router.add_api_route("", post_person, methods=["POST"], status_code=201)
    router.add_api_route("/{group_id}", get_person, methods=["GET"])
    router.add_api_route("/{group_id}", patch_person, methods=["PATCH"])
    router.add_api_route("/{group_id}", del_person, methods=["DELETE"], status_code=204)
    router.add_api_route("/{group_id}/members", put_members, methods=["PUT"])
    router.add_api_route("/{group_id}/now", get_now, methods=["GET"])
    return router

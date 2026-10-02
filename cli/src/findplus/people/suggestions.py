"""People suggestions from tracker names: always a preview, never silent (spec § 2).

Purpose : "Sam Bag", "Sam Bike", "Sam Shoes Red" and "Sam Shoes White"
          become one suggested Person "Sam" with roles; one-word names ask
          "person or pet?"; a name with no owner ("Pixel 11 Pro") is listed
          under "Whose is this?". Nothing is grouped until the owner accepts.
Inputs  : The visible trackers (tracked, or with a sighting), existing groups,
          settings people.dismissed and people.known_devices.
Outputs : build() -> the preview dict; accept() -> the people it created.
Constraints: A tracker already in a person is never moved. A same-named set
          becomes "Turn group Sam into a person"; a same-named person gets
          "New tracker ... looks like Sam's. Add it?". A dismissed suggestion
          stays dismissed until its tracker set changes.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Device, DeviceGroup, Group, LocationObservation
from findplus.db.models_people import PERSON_KINDS
from findplus.device_labels import unique_names
from findplus.labels import display_name
from findplus.people import messages as m
from findplus.people import repo
from findplus.people.naming import NameReading, cluster, cluster_confidence, match_key, read_name
from findplus.state import get_setting, set_setting

DISMISSED = "people.dismissed"
KNOWN = "people.known_devices"


def _json_set(session: Session, key: str) -> set[str]:
    try:
        return set(json.loads(get_setting(session, key) or "[]"))
    except (TypeError, ValueError):
        return set()


def _visible(session: Session) -> list[NameReading]:
    seen = set(session.scalars(select(LocationObservation.device_id).distinct()))
    rows = session.execute(
        select(Device.device_id, Device.label, Device.name, Device.is_tracked)
    ).all()
    return [
        read_name(r.device_id, display_name(r.label, r.name, r.device_id) or r.device_id)
        for r in rows
        if r.is_tracked or r.device_id in seen
    ]


def _groups(session: Session) -> tuple[dict[str, dict], dict[str, int]]:
    """(normalised name -> group info, device_id -> its person/pet group id)."""
    members: dict[int, set[str]] = {}
    for device_id, group_id in session.execute(select(DeviceGroup.device_id, DeviceGroup.group_id)):
        members.setdefault(group_id, set()).add(device_id)
    by_name: dict[str, dict] = {}
    in_person: dict[str, int] = {}
    for g in session.scalars(select(Group)).all():
        ids = members.get(g.id, set())
        by_name[match_key(g.name)] = {"id": g.id, "name": g.name, "kind": g.kind, "members": ids}
        if g.kind in PERSON_KINDS:
            in_person.update(dict.fromkeys(ids, g.id))
    return by_name, in_person


def _member(r: NameReading, shown: dict[str, str]) -> dict:
    return {"device_id": r.device_id, "name": shown.get(r.device_id, r.name),
            "role": r.role, "confidence": r.confidence}  # fmt: skip


def _preview(action: str, name: str, kind: str, members: list[dict]) -> str:
    roles = ", ".join(m.role_word(x["role"]) for x in members)
    if action == "add":
        return m.t("suggest.previewAdd", trackers=m.join_words([x["name"] for x in members]),
                   name=name)  # fmt: skip
    if action == "convert":
        return m.t("suggest.previewConvert", name=name, roles=roles)
    key = "suggest.previewPet" if kind == "pet" else "suggest.previewPerson"
    return m.t(key, name=name, roles=roles)


def _suggestion(owner: str, readings, groups, in_person, shown) -> dict | None:
    """One cluster's suggestion, or None when there is nothing to do."""
    free = [r for r in readings if r.device_id not in in_person]
    existing = groups.get(owner)
    if existing and existing["kind"] in PERSON_KINDS:
        free = [r for r in free if r.device_id not in existing["members"]]
    if not free:
        return None
    action = "create" if existing is None else (
        "add" if existing["kind"] in PERSON_KINDS else "convert")  # fmt: skip
    pet = all(r.looks_like_pet for r in free)
    kind = existing["kind"] if action == "add" else ("pet" if pet else "person")
    name = existing["name"] if existing else readings[0].owner_display
    members = [_member(r, shown) for r in sorted(free, key=lambda r: shown.get(r.device_id, ""))]
    flags = sorted({f for r in free for f in r.flags})
    blocked = []
    if action == "convert":
        blocked = sorted(
            d for d in existing["members"] if in_person.get(d, existing["id"]) != existing["id"]
        )
    ask = action == "create" and all(r.lone_token for r in free)
    return {
        "key": f"{action}:{owner}:{','.join(sorted(r.device_id for r in free))}",
        "action": action, "name": name, "kind": kind, "ask_kind": ask,
        "group_id": existing["id"] if existing else None,
        "confidence": cluster_confidence(free), "flags": flags, "members": members,
        "blocked_device_ids": blocked,
        "preview": _preview(action, name, kind, members),
        "question": m.t("suggest.askKind", name=name) if ask else None,
        "warning": m.t("suggest.lowConfidence", name=name) if flags else None,
    }  # fmt: skip


def build(session: Session) -> dict:
    """The suggestion preview: pure read, nothing is written."""
    shown = unique_names(session)
    readings = _visible(session)
    groups, in_person = _groups(session)
    dismissed = _json_set(session, DISMISSED)
    owned, unowned = cluster(readings)
    suggestions = []
    for owner in sorted(owned):
        s = _suggestion(owner, owned[owner], groups, in_person, shown)
        if s is not None and s["key"] not in dismissed:
            suggestions.append(s)
    unassigned = [
        {**_member(r, shown), "question": m.t("suggest.whose")}
        for r in unowned
        if r.device_id not in in_person
    ]
    known = _json_set(session, KNOWN)
    listed = {x["device_id"] for s in suggestions for x in s["members"]}
    listed |= {u["device_id"] for u in unassigned}
    return {
        "suggestions": suggestions,
        "unassigned": sorted(unassigned, key=lambda u: u["name"].casefold()),
        "new_device_ids": sorted(listed - known),
        "dismissed_count": len(dismissed),
    }


def _mark_known(session: Session) -> None:
    ids = {r.device_id for r in _visible(session)} | _json_set(session, KNOWN)
    set_setting(session, KNOWN, json.dumps(sorted(ids)))


def _accept_one(session: Session, item: dict):
    members = item.get("members") or []
    ids = [x["device_id"] for x in members]
    roles = {x["device_id"]: x["role"] for x in members if "role" in x}
    action = item.get("action", "create")
    if action == "create":
        return repo.create_person(session, name=item["name"], kind=item.get("kind", "person"),
                                  member_ids=ids, roles=roles)  # fmt: skip
    if item.get("group_id") is None:
        raise ValueError(f"{action} needs group_id")
    if action == "convert":
        return repo.convert_group(session, item["group_id"], item.get("kind", "person"), ids, roles)
    if action == "add":
        repo.get_person(session, item["group_id"])
        return repo.add_members(session, item["group_id"], ids, roles)
    raise ValueError("action must be create, convert or add")


def accept(session: Session, accepted: list[dict], dismissed: list[str]) -> dict:
    """Apply the owner's edited choices; all or nothing (the caller rolls back)."""
    people = [_accept_one(session, item) for item in accepted]
    if dismissed:
        keys = _json_set(session, DISMISSED) | set(dismissed)
        set_setting(session, DISMISSED, json.dumps(sorted(keys)))
    _mark_known(session)
    return {"people": [repo.person_dict(p) for p in people], "dismissed": sorted(set(dismissed))}

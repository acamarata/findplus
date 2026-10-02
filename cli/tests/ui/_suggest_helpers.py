"""A realistic /api/people/suggestions body (the owner's names) and a recording route."""

from __future__ import annotations

import json


def member(device_id: str, name: str, role: str) -> dict:
    return {"device_id": device_id, "name": name, "role": role, "confidence": "high"}


_BASE = {"group_id": None, "blocked_device_ids": [], "warning": None, "question": None, "flags": []}


def _suggestion(key: str, name: str, members: list[dict], **extra) -> dict:
    roles = ", ".join(m["role"] for m in members)
    kind = extra.pop("kind", "person")
    preview = f'{"Pet" if kind == "pet" else "Person"} "{name}": {roles}'
    return {
        **_BASE,
        "key": key,
        "action": "create",
        "name": name,
        "kind": kind,
        "ask_kind": False,
        "confidence": "high",
        "members": members,
        "preview": preview,
        **extra,
    }


def payload() -> dict:
    zaid = [
        member("z1", "Zaid Bag", "bag"),
        member("z2", "Zaid Bike", "bike"),
        member("z3", "Zaid Shoes Red", "shoes"),
        member("z4", "Zaid Shoes White", "shoes"),
    ]
    meong = _suggestion("create:meong", "Meong", [member("m1", "Meong", "collar")], kind="pet")
    meong.update(ask_kind=True, confidence="medium", question="Is Meong a person or a pet?")
    rose = _suggestion("create:rose", "Rose", [member("r1", "Rose Bag", "bag")])
    rose.update(confidence="low", flags=["owner_is_colour"])
    pixel = {"device_id": "p1", "name": "Pixel 11 Pro", "role": "phone", "confidence": None}
    return {
        "suggestions": [_suggestion("create:zaid", "Zaid", zaid), meong, rose],
        "unassigned": [{**pixel, "question": "Whose is this?"}],
        "new_device_ids": [],
        "dismissed_count": 0,
    }


async def serve(page, body: dict | None = None, accept_reply: dict | None = None):
    """Serve GET suggestions and record every accept call; returns (gets, posts)."""
    gets: list[int] = []
    posts: list[dict] = []

    async def suggestions(route):
        gets.append(1)
        await route.fulfill(json=body if body is not None else payload())

    async def accept(route):
        posts.append(json.loads(route.request.post_data))
        await route.fulfill(
            json=accept_reply or {"people": [{"id": 5, "name": "Zaid"}], "dismissed": []}
        )

    await page.route("**/api/people/suggestions", suggestions)
    await page.route("**/api/people/suggestions/accept", accept)
    return gets, posts

"""A realistic /api/people/suggestions body (the owner's names) and a route that serves and records."""

from __future__ import annotations

import json


def member(device_id: str, name: str, role: str) -> dict:
    return {"device_id": device_id, "name": name, "role": role, "confidence": "high"}


def payload() -> dict:
    zaid = [
        member("z1", "Zaid Bag", "bag"),
        member("z2", "Zaid Bike", "bike"),
        member("z3", "Zaid Shoes Red", "shoes"),
        member("z4", "Zaid Shoes White", "shoes"),
    ]
    base = {
        "group_id": None,
        "blocked_device_ids": [],
        "warning": None,
        "question": None,
        "flags": [],
    }
    return {
        "suggestions": [
            {
                **base,
                "key": "create:zaid",
                "action": "create",
                "name": "Zaid",
                "kind": "person",
                "ask_kind": False,
                "confidence": "high",
                "members": zaid,
                "preview": 'Person "Zaid": bag, bike, shoes, shoes',
            },
            {
                **base,
                "key": "create:meong",
                "action": "create",
                "name": "Meong",
                "kind": "pet",
                "ask_kind": True,
                "confidence": "medium",
                "members": [member("m1", "Meong", "collar")],
                "preview": 'Pet "Meong": collar',
                "question": "Is Meong a person or a pet?",
            },
            {
                **base,
                "key": "create:rose",
                "action": "create",
                "name": "Rose",
                "kind": "person",
                "ask_kind": False,
                "confidence": "low",
                "flags": ["owner_is_colour"],
                "members": [member("r1", "Rose Bag", "bag")],
                "preview": 'Person "Rose": bag',
            },
        ],
        "unassigned": [
            {
                "device_id": "p1",
                "name": "Pixel 11 Pro",
                "role": "phone",
                "confidence": None,
                "question": "Whose is this?",
            }
        ],
        "new_device_ids": [],
        "dismissed_count": 0,
    }


async def serve(page, body: dict | None = None, accept_reply: dict | None = None):
    """Answer GET suggestions (and /api/people) and record every accept call; returns (gets, posts)."""
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

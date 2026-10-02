"""A realistic /api/places/suggestions body (a school-run family) and recording routes."""

from __future__ import annotations

import json
from copy import deepcopy

HOME = {
    "lat": 41.1,
    "lon": -80.1,
    "radius_m": 100,
    "visits": 21,
    "days": 21,
    "nights": 20,
    "typical": {"days": "every_day", "start_min": 15 * 60 + 30, "end_min": 7 * 60 + 55},
    "kind_guess": "home",
    "trackers": ["Kai", "Mia"],
}
SCHOOL = {
    "lat": 41.12,
    "lon": -80.08,
    "radius_m": 100,
    "visits": 15,
    "days": 15,
    "nights": 0,
    "typical": {"days": "weekdays", "start_min": 8 * 60 + 10, "end_min": 15 * 60},
    "kind_guess": "school_or_work",
    "trackers": ["Kai"],
}
GRANDMA = {
    "lat": 41.05,
    "lon": -80.15,
    "radius_m": 110,
    "visits": 3,
    "days": 3,
    "nights": 0,
    "typical": {"days": "weekends", "start_min": 11 * 60, "end_min": 15 * 60},
    "kind_guess": "regular",
    "trackers": ["Kai", "Mia"],
}


def payload(*items: dict) -> dict:
    return {"candidates": deepcopy(list(items or (HOME, SCHOOL, GRANDMA)))}


async def serve(page, body: dict | None = None):
    """Serve GET suggestions, record dismiss and place POSTs; returns (dismissed, created)."""
    state = {"body": body if body is not None else payload()}
    dismissed: list[dict] = []
    created: list[dict] = []

    async def suggestions(route):
        await route.fulfill(json=state["body"])

    async def dismiss(route):
        spot = json.loads(route.request.post_data)
        dismissed.append(spot)
        left = [c for c in state["body"]["candidates"] if abs(c["lat"] - spot["latitude"]) > 1e-6]
        state["body"] = {"candidates": left}
        await route.fulfill(json={"dismissed": len(dismissed)})

    async def places(route):
        if route.request.method != "POST":
            await route.fallback()
            return
        sent = json.loads(route.request.post_data)
        created.append(sent)
        state["body"] = {
            "candidates": [
                c for c in state["body"]["candidates"] if abs(c["lat"] - sent["latitude"]) > 1e-6
            ]
        }
        await route.fulfill(
            status=201,
            json={
                **sent,
                "id": 99,
                "color": "#3b82f6",
                "kind_guessed": False,
                "notify_rule": None,
                "enter_confirmations": 1,
                "exit_confirmations": 2,
                "devices_inside": [],
                "created_at": "2026-09-27T00:00:00",
                "updated_at": "2026-09-27T00:00:00",
            },
        )

    await page.route("**/api/places/suggestions", suggestions)
    await page.route("**/api/places/suggestions/dismiss", dismiss)
    await page.route("**/api/places", places)
    return dismissed, created

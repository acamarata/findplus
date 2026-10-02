"""Helpers for the Person page tests: a person on the trips fixture and a stub day summary.

The day summary endpoint (GET /api/people/{id}/day) belongs to another package, so these
tests answer it from here with the shape the spec fixes (spec 7.2). Everything else
(people, now, left-behind, timeline, trips) is the real API on the trips fixture server.
"""

# ruff: noqa: E501

from __future__ import annotations

import httpx

HONESTY_TRIPS = "Stays and trips are worked out from sparse, delayed sightings. Times are when a tag was seen, and distances are approximate straight lines, not the road driven."
ALERTS_LATENCY = "Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late."
PRESENCE_STALE = "A tag with no recent fix is stale, not at home and not left behind. Find+ reports it as unknown."


def ensure_person(server: dict, name: str = "Sam") -> int:
    """The id of person `name` (Sam: shoes TAG-SON + bag TAG-MOM), created once per server."""
    base = server["base"]
    for p in httpx.get(f"{base}/api/people").json():
        if p["name"] == name:
            return p["id"]
    body = {
        "name": name,
        "member_ids": ["TAG-SON", "TAG-MOM"],
        "roles": {"TAG-SON": "shoes", "TAG-MOM": "bag"},
    }
    resp = httpx.post(f"{base}/api/people", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def day_body(date: str, pid: int = 1) -> dict:
    """A day summary in the spec 7.2 shape, for the seeded school day."""

    def line(i, hhmm, text, ev=("TAG-SON",)):
        return {
            "id": f"d{i}",
            "kind": "line",
            "at": f"{date}T{hhmm}:00+00:00",
            "local": f"{date}T{hhmm}:00",
            "text": text,
            "evidence": list(ev),
            "confidence": "high",
        }

    return {
        "person": {"id": pid, "name": "Sam"},
        "date": date,
        "timezone": "UTC",
        "now": None,
        "lines": [
            line(0, "00:00", "Overnight at Home", ("TAG-SON", "TAG-MOM")),
            line(1, "07:40", "7:40 AM left Home"),
            line(2, "08:10", "8:10 AM arrived at School"),
            line(3, "15:00", "3:00 PM left School"),
            line(4, "15:40", "3:40 PM arrived at Home"),
        ],
        "left_behind": [],
        "suspect_count": 1,
        "gaps": [],
        "trackers": [],
        "label": HONESTY_TRIPS,
    }


async def stub_day(page, pid: int, fail: bool = False) -> list[str]:
    """Answer /api/people/{pid}/day from `day_body`; returns the list of dates asked for."""
    asked: list[str] = []

    async def handler(route):
        date = route.request.url.split("date=")[1].split("&")[0]
        asked.append(date)
        if fail:
            await route.fulfill(status=500, json={"detail": "summary broke"})
        else:
            await route.fulfill(json=day_body(date, pid))

    await page.route(f"**/api/people/{pid}/day?*", handler)
    return asked


async def open_person(page, server, pid, day_key="school", stub=True):
    """Open `#/person/<pid>?date=<seeded day>` and wait for the page to draw."""
    day = server["days"][day_key]
    if stub:
        await stub_day(page, pid)
    await page.goto(f"{server['base']}/#/person/{pid}?date={day}")
    await page.wait_for_selector(
        "#person-body .person-card, #person-body .empty-state, #person-body [data-pane-error]"
    )
    await page.wait_for_selector("#person-body .skeleton", state="detached")
    return day

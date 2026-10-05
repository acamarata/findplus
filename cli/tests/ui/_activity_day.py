"""Route mocks for the All Activity tests: a day, a person and their events.

Purpose    : Give test_activity_pane.py a controlled day (known times, places,
             accuracies, one suspect fix), one person (Sam, who owns BUSY-00)
             and two arrival/departure events, without touching the real
             database. Only /api/timeline, /api/people and /api/groups/events
             are stubbed.
Inputs     : A Playwright page.
Outputs    : `install_activity_day(page, ...)` returns a dict holding the
             timeline body, the event rows and a list of requested URLs.
Constraints: Neutral names only (Sam, Busy Tag N, School).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ._many_tracks import busy_body

SAM = {
    "id": 4242,
    "name": "Sam",
    "kind": "person",
    "color": "#e11d48",
    "trackers": [{"device_id": "BUSY-00"}],
}


def at(day: str, hh: int, mm: int) -> datetime:
    return datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").astimezone()


def event_row(eid: int, day: str, hh: int, mm: int, kind: str, group_id: int = 4242) -> dict:
    return {
        "id": eid,
        "group_id": group_id,
        "group_name": "Sam",
        "place_id": 1,
        "place_name": "School",
        "event_type": kind,
        "observed_at": at(day, hh, mm).isoformat(),
        "note": "",
    }


def known_body(day: str) -> dict:
    """Two trackers: BUSY-00 (Sam's) at 9:00 and 9:30, BUSY-01 at 9:10 (suspect) and 10:00."""
    body = busy_body(day, tracks=2, points=2)
    stamps = [[(9, 0), (9, 30)], [(9, 10), (10, 0)]]
    for track, times in zip(body["tracks"], stamps, strict=True):
        for pt, (hh, mm) in zip(track["points"], times, strict=True):
            when = at(day, hh, mm)
            pt["observed_at"] = when.isoformat()
            pt["observed_at_local"] = when.isoformat()
    first, second = body["tracks"]
    first["points"][0].update(place_name="Home", accuracy_meters=40.0)
    first["points"][1].update(place_name=None, accuracy_meters=250.0)
    second["points"][0].update(suspect=True, suspect_reason="Jumped 40 km in a minute")
    second["points"][1].update(is_movement=False, accuracy_meters=None)
    return body


async def install_activity_day(page, body_for=known_body, events=None, people=None) -> dict:
    holder = {
        "urls": [],
        "events": list(events or []),
        "people": people or [SAM],
        "fail_events": False,
    }

    async def timeline(r):
        day = r.request.url.split("day=")[1].split("&")[0]
        await r.fulfill(json=body_for(day))

    async def people_route(r):
        await r.fulfill(json=holder["people"])

    async def events_route(r):
        holder["urls"].append(r.request.url)
        if holder["fail_events"]:
            await r.fulfill(status=500, json={"detail": "boom"})
            return
        await r.fulfill(json=holder["events"])

    await page.route("**/api/timeline*", timeline)
    await page.route("**/api/people", people_route)
    await page.route("**/api/groups/events*", events_route)
    return holder


def today() -> str:
    return datetime.now().astimezone().date().isoformat()


def yesterday() -> str:
    return (datetime.now().astimezone().date() - timedelta(days=1)).isoformat()

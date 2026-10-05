"""A synthetic busy day for the dashboard tests: many trackers, many points.

Purpose    : The seeded UI database has two tracks of one point. The folding
             blocks, hour headings and map legend only matter with a real
             roster, so these tests answer GET /api/timeline themselves.
Inputs     : A Playwright page; track and point counts.
Outputs    : `install_busy_day(page, ...)` routes /api/timeline and returns
             the mutable body, so a test can change it between refreshes.
Constraints: Only /api/timeline is stubbed; everything else is the real server.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def point(pid: int, seq: int, when: datetime, lat: float, lon: float, acc: float | None) -> dict:
    local = when.astimezone().isoformat()
    return {
        "id": pid,
        "sequence": seq,
        "observed_at": when.isoformat(),
        "observed_at_local": local,
        "fetched_at": when.isoformat(),
        "latitude": lat,
        "longitude": lon,
        "accuracy_meters": acc,
        "altitude_meters": None,
        "source": "crowdsourced",
        "is_own_report": False,
        "battery_level": None,
        "times_returned": 1,
        "seconds_since_previous": None if seq == 1 else 600.0,
        "meters_from_previous": None if seq == 1 else 120.0,
        "miles_from_previous": None,
        "is_movement": True,
        "gap_before": False,
        "place_name": None,
    }


def busy_body(day: str, tracks: int = 6, points: int = 12) -> dict:
    now = datetime.now().astimezone().replace(microsecond=0)
    out = []
    for t in range(tracks):
        pts = [
            point(
                t * 1000 + i + 1,
                i + 1,
                now - timedelta(minutes=10 * (points - i)),
                41.1 + t * 0.002 + i * 0.0004,
                -80.1 + i * 0.0003,
                25.0 if i % 4 else 250.0,
            )
            for i in range(points)
        ]
        out.append(
            {
                "device_id": f"BUSY-{t:02d}",
                "device_name": f"Busy Tag {t}",
                "points": pts,
                "stats": {
                    "observation_count": points,
                    "movement_count": points,
                    "first_observed_at_local": pts[0]["observed_at_local"],
                    "last_observed_at_local": pts[-1]["observed_at_local"],
                    "approximate_distance_miles": 1.0,
                    "longest_gap_seconds": 600,
                    "time_span_seconds": 600 * points,
                    "distance_label": "Approximate distance",
                },
            }
        )
    return {
        "day": day,
        "timezone": "UTC",
        "device_id": None,
        "movement_threshold_meters": 50,
        "gap_threshold_minutes": 60,
        "path_disclaimer": "Observed path.",
        "tracks": out,
        "total_observations": tracks * points,
    }


async def install_busy_day(page, tracks: int = 6, points: int = 12) -> dict:
    holder: dict = {}

    async def route(r):
        day = r.request.url.split("day=")[1].split("&")[0]
        if "body" not in holder or holder["body"]["day"] != day:
            holder["body"] = busy_body(day, tracks, points)
        await r.fulfill(json=holder["body"])

    holder["route"] = route
    await page.route("**/api/timeline*", route)
    return holder


async def settle_map(page):
    """Wait out the boot fit's zoom animation: a setZoom made during it is overwritten."""
    idle = "() => import('/static/app/state.js').then((m) => !m.state.map?._animatingZoom)"
    await page.wait_for_function(idle)
    await page.wait_for_timeout(300)
    await page.wait_for_function(idle)


__all__ = ["busy_body", "install_busy_day", "settle_map"]

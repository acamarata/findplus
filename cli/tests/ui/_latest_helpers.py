"""Shared helpers for the Latest tab and tracker focus tests (dashboard 1.3).

Purpose    : Boot the dashboard on the day-story fixture server, make one person
             (Alex, owning the tracker TAG-SON) so the other tracker (TAG-MOM,
             "Mia") belongs to nobody, and read the focus state.
Inputs     : `trips_server` (module scoped) and `trips_page` from conftest.
Outputs    : `ensure_alex`, `boot`, `focus_state`, `FOCUS_EVENT`.
Constraints: Neutral names only. Nothing here touches ~/.findplus or the network.
"""

from __future__ import annotations

import httpx

from ._many_tracks import settle_map


def ensure_alex(server: dict) -> int:
    """Person Alex with only TAG-SON, so TAG-MOM stays a tracker with no person."""
    base = server["base"]
    for p in httpx.get(f"{base}/api/people").json():
        if p["name"] == "Alex":
            return p["id"]
    body = {"name": "Alex", "member_ids": ["TAG-SON"], "roles": {"TAG-SON": "shoes"}}
    resp = httpx.post(f"{base}/api/people", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def boot(page, server: dict, path: str = "/", width: int = 1280) -> None:
    """Open the dashboard and wait until it is ready and the map has settled."""
    await page.set_viewport_size({"width": width, "height": 800})
    await page.goto(server["base"] + path)
    await page.wait_for_selector("#app-shell[data-fp-ready]", timeout=20000)
    await settle_map(page)


async def focus_state(page) -> dict:
    """The device filter, how many tracks the timeline holds, and the focus header's name."""
    return await page.evaluate(
        """async () => {
            const s = (await import('/static/app/state.js')).state;
            const name = document.getElementById('fp-focus-name');
            return {
              filter: s.deviceFilter,
              tracks: s.timeline ? s.timeline.tracks.map((t) => t.device_id) : [],
              name: name ? name.textContent : null,
              hash: window.location.hash,
            };
        }"""
    )


async def dispatch_focus(page, device_id: str, point_id: int | None = None) -> None:
    """What the map popup and the Activity lines do."""
    detail = {"device_id": device_id}
    if point_id is not None:
        detail["point_id"] = point_id
    await page.evaluate(
        "d => window.dispatchEvent(new CustomEvent('findplus:focus-tracker', { detail: d }))",
        detail,
    )


async def active_tab(page) -> str:
    return await page.evaluate("document.querySelector('.fp-tabs .fp-tab.active').dataset.tab")

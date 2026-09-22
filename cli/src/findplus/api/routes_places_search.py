"""Address search: opt-in geocoding through OpenStreetMap's Nominatim.

Purpose    : Let the place dialog turn a typed address into a latitude and
             longitude without the browser ever talking to a third party --
             the daemon makes the one outbound call, so the dashboard's CSP
             stays tight and the request carries a proper User-Agent instead
             of whatever a fetch() from the page would send.
Inputs     : GET /api/places/search?q=<text>, fired only when the user
             presses Search (places_dialog.js never calls this on keystroke
             -- ruling R-P2-30.2).
Outputs    : A list of up to 5 {display_name, latitude, longitude} dicts.
Constraints:
    - Nominatim's usage policy caps this at one request per second and asks
      for a descriptive User-Agent identifying the application. The daemon
      is single-user and single-process, so one shared last-request
      timestamp behind a lock is enough to honour the limit; a caller that
      arrives early sleeps out the remainder instead of being refused.
    - 5 second timeout. A slow or unreachable Nominatim is a 502/504, never
      a request the dashboard waits on indefinitely.
    - Gated by SessionAuthMiddleware like every /api/ path not in _PUBLIC.
    - `_fetch_from_nominatim` is the one seam tests replace; the autouse
      network-block fixture (cli/tests/conftest.py) would otherwise turn an
      un-mocked call into a connection error, never a real request.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from findplus import __version__

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_TIMEOUT_SECONDS = 5.0
_MIN_INTERVAL_SECONDS = 1.0
_RESULT_LIMIT = 5
_USER_AGENT = f"FindPlus/{__version__} (https://github.com/acamarata/findplus)"

_throttle_lock = threading.Lock()
_last_request_monotonic: float | None = None


def _wait_for_throttle_slot() -> None:
    """Block, if needed, so outbound Nominatim requests never run closer
    than 1 second apart, process-wide."""
    global _last_request_monotonic
    with _throttle_lock:
        now = time.monotonic()
        if _last_request_monotonic is not None:
            remaining = _MIN_INTERVAL_SECONDS - (now - _last_request_monotonic)
            if remaining > 0:
                time.sleep(remaining)
                now = time.monotonic()
        _last_request_monotonic = now


def _fetch_from_nominatim(query: str) -> httpx.Response:
    params = {"format": "jsonv2", "q": query, "limit": str(_RESULT_LIMIT)}
    headers = {"User-Agent": _USER_AGENT}
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
        return client.get(NOMINATIM_URL, params=params, headers=headers)


def _parse_results(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:_RESULT_LIMIT]:
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                {
                    "display_name": str(row["display_name"]),
                    "latitude": float(row["lat"]),
                    "longitude": float(row["lon"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def get_search(q: str = Query(default="")) -> list[dict[str, Any]]:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q must not be blank")

    _wait_for_throttle_slot()

    try:
        resp = _fetch_from_nominatim(query)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="address search timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="address search unreachable") from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"address search returned HTTP {resp.status_code}"
        )
    try:
        rows = resp.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502, detail="address search returned malformed data"
        ) from exc
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="address search returned malformed data")
    return _parse_results(rows)


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/places", tags=["places"])
    router.add_api_route("/search", get_search, methods=["GET"])
    return router

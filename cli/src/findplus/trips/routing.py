"""Optional "likely route along roads" through an OSRM-compatible server.

Purpose    : Draw a road-following line through the sightings of one trip.
Inputs     : An endpoint base URL the user set (`routing.endpoint`) and the
             trip's fixes.
Outputs    : A dict with a GeoJSON LineString, a `style` ("solid" when the
             server answered, "dashed" for the straight-line fallback), the
             honesty `label`, and `source` ("match", "route" or "straight").
Constraints: PRIVACY. Nothing is sent unless the user configured an endpoint;
             with none, `likely_route` makes no request and returns straight
             segments. The points go to THAT server only, so the setting text
             says so. No public demo server is ever built in. Any failure
             (timeout, refusal, bad JSON, no match) degrades to straight dashed
             segments and never raises. The result is a guess between sparse
             sightings, not the road driven; the label says so.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from findplus import honesty
from findplus.logging_setup import get_logger
from findplus.trips.models import Fix

log = get_logger(__name__)

SETTING_KEY = "routing.endpoint"
#: OSRM URLs carry every coordinate; keep the request small.
MAX_POINTS = 60
TIMEOUT_S = 8.0
MAX_BODY_BYTES = 2_000_000


def normalize_endpoint(value: str | None) -> str:
    """Return a clean base URL, '' when unset. Raises ValueError for an unusable one."""
    text = (value or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Routing server must be an http:// or https:// address.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(
            "Routing server address must not contain credentials, a query or a fragment."
        )
    return text.rstrip("/")


def _sample(points: list[Fix]) -> list[Fix]:
    """At most MAX_POINTS fixes, keeping the first and last and spacing the rest evenly."""
    if len(points) <= MAX_POINTS:
        return points
    step = (len(points) - 1) / (MAX_POINTS - 1)
    return [points[round(i * step)] for i in range(MAX_POINTS)]


def _coords(points: list[Fix]) -> str:
    return ";".join(f"{p.lon:.6f},{p.lat:.6f}" for p in points)


def straight_line(points: list[Fix], reason: str) -> dict[str, Any]:
    """The fallback: dashed straight segments through the sightings."""
    return {
        "geometry": {"type": "LineString", "coordinates": [[p.lon, p.lat] for p in points]},
        "style": "dashed",
        "source": "straight",
        "label": honesty.TRIPS_APPROXIMATE,
        "reason": reason,
    }


def _get_json(client: httpx.Client, url: str, params: dict[str, str]) -> dict[str, Any] | None:
    try:
        resp = client.get(url, params=params, timeout=TIMEOUT_S)
        if resp.status_code != 200 or len(resp.content) > MAX_BODY_BYTES:
            return None
        body = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    return body if isinstance(body, dict) and body.get("code") == "Ok" else None


def _line_from(body: dict[str, Any] | None, key: str) -> list[list[float]]:
    """Join the GeoJSON geometries of every match/route in an OSRM answer."""
    coords: list[list[float]] = []
    for item in (body or {}).get(key) or []:
        geom = item.get("geometry") or {}
        if geom.get("type") == "LineString":
            coords.extend(geom.get("coordinates") or [])
    return coords


def _try_match(client: httpx.Client, base: str, pts: list[Fix]) -> list[list[float]]:
    radii = ";".join(str(int(min(max(p.acc, 25), 200))) for p in pts)
    params = {"geometries": "geojson", "overview": "full", "radiuses": radii, "gaps": "ignore"}
    url = f"{base}/match/v1/driving/{_coords(pts)}"
    return _line_from(_get_json(client, url, params), "matchings")


def _try_route(client: httpx.Client, base: str, pts: list[Fix]) -> list[list[float]]:
    params = {"geometries": "geojson", "overview": "full", "steps": "false"}
    url = f"{base}/route/v1/driving/{_coords(pts)}"
    return _line_from(_get_json(client, url, params), "routes")


def likely_route(
    endpoint: str | None, points: list[Fix], client: httpx.Client | None = None
) -> dict[str, Any]:
    """A road-following line through `points`, or the dashed straight fallback.

    Tries /match first (it snaps noisy fixes to roads), then /route (it joins
    the fixes with the quickest road path). `client` is injectable for tests.
    """
    if len(points) < 2:
        return straight_line(points, "A trip needs at least two sightings.")
    try:
        base = normalize_endpoint(endpoint)
    except ValueError:
        return straight_line(points, "The routing server address is not valid.")
    if not base:
        return straight_line(points, "Road routes are off.")
    pts = _sample(points)
    own = client is None
    http = client or httpx.Client(follow_redirects=False)
    try:
        for source, attempt in (("match", _try_match), ("route", _try_route)):
            line = attempt(http, base, pts)
            if len(line) >= 2:
                geometry = {"type": "LineString", "coordinates": line}
                return {
                    "geometry": geometry,
                    "style": "solid",
                    "source": source,
                    "label": honesty.ROUTE_LIKELY,
                    "reason": None,
                }
    finally:
        if own:
            http.close()
    log.info("routing_unavailable")
    return straight_line(points, "The routing server did not return a route.")

"""The `routing.endpoint` key of GET/PATCH /api/settings.

Purpose    : The opt-in road-route server used to be readable only through its own
             GET/POST /api/settings/routing.endpoint pair, so the combined settings
             body (and anything that mirrors it) never showed it. It now rides along.
Inputs     : The PATCH body's raw dict; a key's presence is the signal, and an empty
             or null value switches routing off.
Outputs    : The stored endpoint ("" when off) for the GET body; a write through the
             same trips.routing.normalize_endpoint the dedicated route uses.
Constraints: Validation is normalize_endpoint's, shared with the dedicated route, so
             the two cannot disagree. A bad value raises ValueError (the route turns
             it into a 422) and nothing is written. The privacy notice stays with
             the dedicated route's reply.
"""

from __future__ import annotations

from typing import Any

from findplus.state import get_setting, set_setting
from findplus.trips.routing import SETTING_KEY, normalize_endpoint

WIRE_KEY = SETTING_KEY


def routing_field(session) -> str:
    return get_setting(session, SETTING_KEY) or ""


def write_routing_field(session, raw_body: dict[str, Any]) -> None:
    """Store a PATCH's `routing.endpoint`, or clear it with an empty or null value."""
    if WIRE_KEY not in raw_body:
        return
    value = raw_body[WIRE_KEY]
    if value is not None and not isinstance(value, str):
        raise ValueError("routing.endpoint must be a URL string, or empty to turn routing off")
    clean = normalize_endpoint(value)
    set_setting(session, SETTING_KEY, clean or None)

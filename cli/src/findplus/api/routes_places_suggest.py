"""Places we noticed: GET /api/places/suggestions and POST /api/places/suggestions/dismiss.

Purpose    : Offer likely places (home, school, a regular stop) found from the
             stays in the last 30 days, for the owner to name. Nothing is
             created here; the owner saves one through POST /api/places.
Inputs     : Optional `timezone` (IANA name) and `date` (last day looked at);
             dismiss takes {latitude, longitude}.
Outputs    : {"candidates": [{lat, lon, radius_m, visits, days, nights, typical,
             kind_guess, trackers}]}. Dismiss answers {"dismissed": <count>}.
Constraints: Gated by the lock middleware like every /api/ path. Read-only
             except dismiss, which only remembers a spot. Registered before the
             /{place_id} routes in routes_places.build_router().
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from findplus.db.session import session_scope
from findplus.places.suggest_service import dismiss, suggestions
from findplus.timeline import local_zone

from ._helpers import _parse_day


class Dismiss(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


def get_suggestions(
    timezone: str | None = Query(default=None),
    date: str | None = Query(default=None, description="Last local day to look at; default today"),
) -> dict[str, Any]:
    with session_scope() as s:
        return suggestions(s, local_zone(timezone), today=_parse_day(date))


def post_dismiss(body: Dismiss) -> dict[str, Any]:
    with session_scope() as s:
        count = dismiss(s, body.latitude, body.longitude)
        s.commit()
        return {"dismissed": count}


def register(router: APIRouter) -> None:
    router.add_api_route("/suggestions", get_suggestions, methods=["GET"])
    router.add_api_route("/suggestions/dismiss", post_dismiss, methods=["POST"])

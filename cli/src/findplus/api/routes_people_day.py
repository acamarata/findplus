"""People day routes: the daily summary and "send it now" (spec § 7.2).

Purpose    : GET /api/people/{id}/day returns one person's local day as plain-words
             lines (people/day_load.day_payload). POST /api/people/{id}/day/send
             sends that day's summary to the connected Telegram chat right now.
Inputs     : `date` (YYYY-MM-DD, default today) and `timezone` (IANA, default the
             computer's zone), as query parameters (GET) or a JSON body (POST).
Outputs    : The summary dict, or {sent, channel, targets[], text} for a send.
Constraints: Read only except for the Telegram message. Gated by the lock
             middleware like every /api/ path, so both 401 while locked. A manual
             send writes no digest_runs row: it never uses up the evening one.
             409 when no chat is connected, 502 when no chat accepted the message.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from findplus.db.session import session_scope
from findplus.people import messages as m
from findplus.people import repo
from findplus.people.day_load import day_payload
from findplus.people.day_render import render_text
from findplus.service import digest_send
from findplus.timeline import local_zone

from ._helpers import _parse_day
from ._people_http import map_value_error


class DaySendBody(BaseModel):
    date: str | None = None
    timezone: str | None = None


def _zone(name: str | None) -> ZoneInfo:
    try:
        return local_zone(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"Unknown timezone {name!r}.") from exc


def _summary(group_id: int, date: str | None, timezone: str | None) -> dict[str, Any]:
    tz = _zone(timezone)
    now = datetime.now(UTC)
    day = _parse_day(date) or now.astimezone(tz).date()
    with session_scope() as s:
        try:
            group = repo.get_person(s, group_id)
        except ValueError as exc:
            raise map_value_error(exc) from exc
        return day_payload(s, group, day, tz, now)


def get_day(
    group_id: int,
    date: str | None = Query(default=None, description="YYYY-MM-DD local date; default today"),
    timezone: str | None = Query(default=None, description="IANA zone; default the computer's"),
) -> dict[str, Any]:
    """One person's day: lines with the trackers behind each, gaps, left-behind, a footer."""
    return _summary(group_id, date, timezone)


def post_send(group_id: int, body: DaySendBody | None = None) -> dict[str, Any]:
    """Send that day's summary to the connected Telegram chat now."""
    body = body or DaySendBody()
    creds = digest_send.telegram_creds()
    if creds is None:
        raise HTTPException(status_code=409, detail=m.t("day.noChannel"))
    payload = _summary(group_id, body.date, body.timezone)
    text = render_text(payload)
    results = digest_send.send_to_targets(text, creds)
    targets = [{"target": r.target, "ok": r.ok, "error": r.error} for r in results]
    if not any(r.ok for r in results):
        detail = next((r.error for r in results if r.error), "Telegram did not accept the message.")
        raise HTTPException(status_code=502, detail=detail)
    return {"sent": True, "channel": "telegram", "targets": targets, "text": text}


def register(router: APIRouter) -> None:
    router.add_api_route("/{group_id}/day", get_day, methods=["GET"])
    router.add_api_route("/{group_id}/day/send", post_send, methods=["POST"])

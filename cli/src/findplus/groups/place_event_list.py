"""Listing a group's place events (arrivals and departures) for the API and CLI.

Purpose : Split out of groups/repo.py at the 300-line file cap; repo.py
          re-exports `list_group_place_events` so every caller keeps its import.
Inputs  : An open Session plus optional group/place/time filters.
Outputs : Plain dicts, newest first, each with the one-sentence `note`
          (specs/api-contract.md § routes_groups.py).
Constraints: Read-only; never commits.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Group, GroupPlaceEvent, Place
from findplus.groups.quorum import group_event_note, stale_note_for_count


def _group_place_events_stmt(
    group_id: int | None, place_id: int | None, since: datetime | None, until: datetime | None,
    limit: int,
):  # fmt: skip
    stmt = (
        select(GroupPlaceEvent, Group.name.label("group_name"), Place.name.label("place_name"))
        .join(Group, GroupPlaceEvent.group_id == Group.id)
        .join(Place, GroupPlaceEvent.place_id == Place.id)
    )
    if group_id is not None:
        stmt = stmt.where(GroupPlaceEvent.group_id == group_id)
    if place_id is not None:
        stmt = stmt.where(GroupPlaceEvent.place_id == place_id)
    if since is not None:
        stmt = stmt.where(GroupPlaceEvent.observed_at >= since)
    if until is not None:
        stmt = stmt.where(GroupPlaceEvent.observed_at <= until)
    return stmt.order_by(GroupPlaceEvent.observed_at.desc()).limit(min(limit, 1000))


def _group_place_event_dict(e, group_name: str, place_name: str) -> dict:
    return {
        "id": e.id,
        "group_id": e.group_id,
        "group_name": group_name,
        "place_id": e.place_id,
        "place_name": place_name,
        "event_type": e.event_type,
        "observed_at": e.observed_at,
        "members_crossed": e.members_crossed,
        "members_considered": e.members_considered,
        "members_stale": e.members_stale,
        "confidence": e.confidence,
        # api-contract.md § routes_groups.py pins `note` on this route.
        "note": group_event_note(
            crossed=e.members_crossed,
            considered=e.members_considered,
            event_type=e.event_type,
            place=place_name,
            stale_note=stale_note_for_count(e.members_stale),
        ),
        "notified_at": e.notified_at,
    }


def list_group_place_events(
    session: Session,
    *,
    group_id: int | None = None,
    place_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
) -> list[dict]:
    stmt = _group_place_events_stmt(group_id, place_id, since, until, limit)
    return [
        _group_place_event_dict(row.GroupPlaceEvent, row.group_name, row.place_name)
        for row in session.execute(stmt).all()
    ]

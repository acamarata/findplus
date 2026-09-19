"""Places repository: CRUD, event log and current presence.

Purpose : Single source of truth for place data, shared by routes_places.py
          and cli/places.py so validation lives in exactly one place.
Inputs  : An open Session (caller-owned transaction) plus plain arguments.
Outputs : ORM rows (Place, PlaceEvent) or plain dicts (current_presence).
Constraints: Never commits. Write functions raise ValueError with an exact
          message so callers map it to an HTTP status without guessing.
Reuse: session pattern matches findplus.state (select(), session.get()).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Device, Place, PlaceEvent, PlaceState


def list_places(session: Session) -> list[Place]:
    """Every saved place, alphabetical, with `_devices_inside` attached."""
    rows = list(session.scalars(select(Place).order_by(Place.name)).all())
    for row in rows:
        row._devices_inside = list(
            session.scalars(
                select(PlaceState.device_id).where(
                    PlaceState.place_id == row.id, PlaceState.state == "inside"
                )
            ).all()
        )
    return rows


def _validate_place_fields(
    *,
    name: str | None = None,
    latitude_e7: int | None = None,
    longitude_e7: int | None = None,
    radius_meters: int | None = None,
    enter_confirmations: int | None = None,
    exit_confirmations: int | None = None,
) -> None:
    if name is not None and not (1 <= len(name) <= 64):
        raise ValueError("name must be 1-64 characters")
    if radius_meters is not None and not (20 <= radius_meters <= 5000):
        raise ValueError("radius_meters must be 20-5000")
    if latitude_e7 is not None and not (-900000000 <= latitude_e7 <= 900000000):
        raise ValueError("latitude_e7 out of range")
    if longitude_e7 is not None and not (-1800000000 <= longitude_e7 <= 1800000000):
        raise ValueError("longitude_e7 out of range")
    if enter_confirmations is not None and not (1 <= enter_confirmations <= 5):
        raise ValueError("enter_confirmations must be 1-5")
    if exit_confirmations is not None and not (1 <= exit_confirmations <= 5):
        raise ValueError("exit_confirmations must be 1-5")


def create_place(
    session: Session,
    *,
    name: str,
    latitude_e7: int,
    longitude_e7: int,
    radius_meters: int,
    color: str = "#2f80ed",
    enter_confirmations: int = 1,
    exit_confirmations: int = 2,
) -> Place:
    _validate_place_fields(
        name=name,
        latitude_e7=latitude_e7,
        longitude_e7=longitude_e7,
        radius_meters=radius_meters,
        enter_confirmations=enter_confirmations,
        exit_confirmations=exit_confirmations,
    )
    if session.scalar(select(Place.id).where(Place.name == name)) is not None:
        raise ValueError(f"place name {name!r} already exists")
    now = datetime.now(UTC)
    place = Place(
        name=name,
        latitude_e7=latitude_e7,
        longitude_e7=longitude_e7,
        radius_meters=radius_meters,
        color=color,
        enter_confirmations=enter_confirmations,
        exit_confirmations=exit_confirmations,
        created_at=now,
        updated_at=now,
    )
    session.add(place)
    session.flush()
    return place


def update_place(
    session: Session,
    place_id: int,
    *,
    name: str | None = None,
    latitude_e7: int | None = None,
    longitude_e7: int | None = None,
    radius_meters: int | None = None,
    color: str | None = None,
    enter_confirmations: int | None = None,
    exit_confirmations: int | None = None,
) -> Place:
    place = session.get(Place, place_id)
    if place is None:
        raise ValueError(f"place {place_id} not found")
    _validate_place_fields(
        name=name,
        latitude_e7=latitude_e7,
        longitude_e7=longitude_e7,
        radius_meters=radius_meters,
        enter_confirmations=enter_confirmations,
        exit_confirmations=exit_confirmations,
    )
    if name is not None and name != place.name:
        if session.scalar(select(Place.id).where(Place.name == name)) is not None:
            raise ValueError(f"place name {name!r} already exists")
        place.name = name
    if radius_meters is not None:
        place.radius_meters = radius_meters
    if latitude_e7 is not None:
        place.latitude_e7 = latitude_e7
    if longitude_e7 is not None:
        place.longitude_e7 = longitude_e7
    if color is not None:
        place.color = color
    if enter_confirmations is not None:
        place.enter_confirmations = enter_confirmations
    if exit_confirmations is not None:
        place.exit_confirmations = exit_confirmations
    place.updated_at = datetime.now(UTC)
    session.flush()
    return place


def delete_place(session: Session, place_id: int) -> None:
    place = session.get(Place, place_id)
    if place is None:
        raise ValueError(f"place {place_id} not found")
    session.delete(place)
    session.flush()


def list_place_events(
    session: Session,
    *,
    place_id: int | None = None,
    device_id: str | None = None,
    group_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
) -> list[PlaceEvent]:
    stmt = (
        select(PlaceEvent, Place.name.label("place_name"), Device.name.label("device_name"))
        .join(Place, PlaceEvent.place_id == Place.id)
        .join(Device, PlaceEvent.device_id == Device.device_id)
    )
    if place_id is not None:
        stmt = stmt.where(PlaceEvent.place_id == place_id)
    if device_id is not None:
        stmt = stmt.where(PlaceEvent.device_id == device_id)
    if group_id is not None:
        stmt = stmt.where(PlaceEvent.group_id == group_id)
    if since is not None:
        stmt = stmt.where(PlaceEvent.observed_at >= since)
    if until is not None:
        stmt = stmt.where(PlaceEvent.observed_at <= until)
    stmt = stmt.order_by(PlaceEvent.observed_at.desc()).limit(min(limit, 1000))

    result = []
    for row in session.execute(stmt).all():
        row.PlaceEvent._place_name = row.place_name
        row.PlaceEvent._device_name = row.device_name
        result.append(row.PlaceEvent)
    return result


def current_presence(session: Session, *, device_id: str | None = None) -> list[dict]:
    stmt = select(PlaceState, Place.name.label("place_name")).join(
        Place, PlaceState.place_id == Place.id
    )
    if device_id is not None:
        stmt = stmt.where(PlaceState.device_id == device_id)
    rows = session.execute(stmt).all()
    return [
        {
            "device_id": r.PlaceState.device_id,
            "place_id": r.PlaceState.place_id,
            "place_name": r.place_name,
            "state": r.PlaceState.state,
            "since_observed_at": r.PlaceState.since_observed_at,
        }
        for r in rows
    ]

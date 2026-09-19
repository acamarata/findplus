"""CLI for managing saved places.

Purpose    : list/add/edit/remove places and view geofence events without a
             running daemon.
Inputs     : Click options/arguments (see specs/cli-reference.md § places).
Outputs    : Table/JSON/CSV to stdout; a place id or error to stderr on add.
Constraints: Direct DB access via session_scope — no HTTP calls to the daemon.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime

import click

from findplus.db.session import session_scope
from findplus.places.repo import (
    create_place,
    delete_place,
    list_place_events,
    list_places,
    update_place,
)

places_cmd = click.Group(name="places", help="Manage saved places and view geofence events.")

_PLACE_KEYS = (
    "id",
    "name",
    "latitude",
    "longitude",
    "radius_meters",
    "color",
    "enter_confirmations",
    "exit_confirmations",
)
_EVENT_KEYS = ("id", "place", "device", "type", "observed_at", "confidence")


def _place_values(r) -> tuple:
    return (
        r.id,
        r.name,
        r.latitude_e7 / 1e7,
        r.longitude_e7 / 1e7,
        r.radius_meters,
        r.color,
        r.enter_confirmations,
        r.exit_confirmations,
    )


def _event_values(r) -> tuple:
    return (
        r.id,
        getattr(r, "_place_name", ""),
        getattr(r, "_device_name", ""),
        r.event_type,
        r.observed_at.isoformat() + "Z",
        r.confidence,
    )


def _run(fn, *args, **kwargs):
    """Call a repo write function; print + exit(1) on ValueError."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@places_cmd.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def list_places_cmd(as_json: bool) -> None:
    """List every saved place."""
    with session_scope() as s:
        rows = list_places(s)
    if as_json:
        out = [dict(zip(_PLACE_KEYS, _place_values(r), strict=True)) for r in rows]
        click.echo(json.dumps(out, indent=2))
        return
    click.echo(
        f"{'ID':<6}{'NAME':<26}{'LAT':>10}{'LON':>12}{'RADIUS':>8}{'COLOR':<10}{'ENTER':>6}{'EXIT':>5}"
    )
    for r in rows:
        i, name, lat, lon, radius, color, enter, exit_ = _place_values(r)
        click.echo(
            f"{i:<6}{name:<26}{lat:>10.6f}{lon:>12.6f}{radius:>8}{color:<10}{enter:>6}{exit_:>5}"
        )


@places_cmd.command("add")
@click.argument("name")
@click.option("--lat", required=True, type=float, help="Latitude (decimal degrees).")
@click.option("--lon", required=True, type=float, help="Longitude (decimal degrees).")
@click.option("--radius", "radius_meters", required=True, type=int, help="Radius in metres.")
@click.option("--color", default="#2f80ed", show_default=True)
@click.option("--enter-confirmations", default=1, type=int, show_default=True)
@click.option("--exit-confirmations", default=2, type=int, show_default=True)
def add_place_cmd(name, lat, lon, radius_meters, color, enter_confirmations, exit_confirmations):
    """Save a new place."""
    kwargs = {
        "name": name,
        "latitude_e7": round(lat * 1e7),
        "longitude_e7": round(lon * 1e7),
        "radius_meters": radius_meters,
        "color": color,
        "enter_confirmations": enter_confirmations,
        "exit_confirmations": exit_confirmations,
    }
    with session_scope() as s:
        p = _run(create_place, s, **kwargs)
    click.echo(f"Created place {p.id}: {p.name}")


@places_cmd.command("edit")
@click.argument("place_id", type=int)
@click.option("--name", default=None)
@click.option("--lat", default=None, type=float)
@click.option("--lon", default=None, type=float)
@click.option("--radius", "radius_meters", default=None, type=int)
@click.option("--color", default=None)
@click.option("--enter-confirmations", default=None, type=int)
@click.option("--exit-confirmations", default=None, type=int)
def edit_place_cmd(
    place_id, name, lat, lon, radius_meters, color, enter_confirmations, exit_confirmations
):
    """Update one or more fields of an existing place."""
    fields = {
        "name": name,
        "radius_meters": radius_meters,
        "color": color,
        "enter_confirmations": enter_confirmations,
        "exit_confirmations": exit_confirmations,
    }
    kwargs = {k: v for k, v in fields.items() if v is not None}
    if lat is not None:
        kwargs["latitude_e7"] = round(lat * 1e7)
    if lon is not None:
        kwargs["longitude_e7"] = round(lon * 1e7)
    with session_scope() as s:
        _run(update_place, s, place_id, **kwargs)
    click.echo(f"Updated place {place_id}")


@places_cmd.command("remove")
@click.argument("place_id", type=int)
@click.option("--yes", is_flag=True, help="Confirm removal.")
def remove_place_cmd(place_id, yes):
    """Delete a place. Requires --yes."""
    if not yes:
        click.echo("Pass --yes to confirm removal.", err=True)
        sys.exit(1)
    with session_scope() as s:
        _run(delete_place, s, place_id)
    click.echo(f"Removed place {place_id}")


@places_cmd.command("events")
@click.option("--place", "place_id", default=None, type=int)
@click.option("--device-id", default=None)
@click.option("--since", default=None)
@click.option("--until", default=None)
@click.option("--limit", default=200, type=int, show_default=True)
@click.option(
    "--format",
    "fmt",
    default="table",
    show_default=True,
    type=click.Choice(["table", "csv", "json"]),
)
def events_cmd(place_id, device_id, since, until, limit, fmt):
    """List geofence ENTER/EXIT events."""
    kwargs = {
        "place_id": place_id,
        "device_id": device_id,
        "since": _parse_iso(since),
        "until": _parse_iso(until),
        "limit": limit,
    }
    with session_scope() as s:
        rows = list_place_events(s, **kwargs)
    records = [_event_values(r) for r in rows]

    if fmt == "json":
        out = [dict(zip(_EVENT_KEYS, rec, strict=True)) for rec in records]
        click.echo(json.dumps(out, indent=2))
    elif fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(_EVENT_KEYS)
        w.writerows(records)
    else:
        click.echo(f"{'ID':<6}{'PLACE':<20}{'DEVICE':<20}{'TYPE':<6}{'OBSERVED':<26}{'CONF'}")
        for i, place, device, etype, observed, conf in records:
            click.echo(f"{i:<6}{place:<20}{device:<20}{etype:<6}{observed:<26}{conf}")


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

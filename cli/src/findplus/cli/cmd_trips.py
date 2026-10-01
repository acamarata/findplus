"""`findplus trips`: stays and trips for one device and day, as a table or JSON.

Purpose    : The terminal view of the same segmentation the dashboard and the
             MCP `get_trips` tool use. Reads the local database only.
Inputs     : --device-id (optional when exactly one device is tracked),
             --date, --days, --timezone, --json.
Outputs    : A readable table of stays, trips and gaps, or the API payload.
Constraints: Distances are approximate straight lines and say so. Never
             queries Google; never sends anything anywhere.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime

import click

from findplus import honesty
from findplus.db.session import session_scope

from ._fmt import _prep, _render_table


def _pick_device(session, device_id: str | None) -> str:
    """The given id, or the only tracked device; otherwise a clear usage error."""
    from sqlalchemy import select

    from findplus.db.models import Device

    if device_id:
        if session.get(Device, device_id) is None:
            raise click.ClickException(f"Unknown device id {device_id!r}. Run `findplus devices`.")
        return device_id
    tracked = list(session.scalars(select(Device).where(Device.is_tracked.is_(True))))
    if len(tracked) == 1:
        return tracked[0].device_id
    raise click.UsageError(
        "Pass --device-id (see `findplus devices`); more than one device exists."
    )


def _hhmm(local_iso: str | None, utc_iso: str) -> str:
    return (local_iso or utc_iso)[11:16]


def _mins(value: float) -> str:
    total = round(value)
    return f"{total // 60}h {total % 60:02d}m" if total >= 60 else f"{total}m"


def _km(meters: int) -> str:
    return f"~{meters / 1000:.1f} km"


def _print_stays(payload: dict) -> None:
    rows = [
        (
            _hhmm(s["start_local"], s["start_at"]),
            _hhmm(s["end_local"], s["end_at"]),
            _mins(s["duration_minutes"]),
            s["label"],
            s["fix_count"],
        )
        for s in payload["stays"]
    ]
    click.secho("\nStays", bold=True)
    _render_table(("FROM", "TO", "LENGTH", "PLACE", "FIXES"), "<<<<>", rows)


def _print_trips(payload: dict) -> None:
    names = {s["id"]: s["label"] for s in payload["stays"]}
    rows = [
        (
            _hhmm(t["start_local"], t["start_at"]),
            _hhmm(t["end_local"], t["end_at"]),
            _mins(t["duration_minutes"]),
            f"{names.get((t['from'] or {}).get('stay_id'), '?')} -> "
            f"{names.get((t['to'] or {}).get('stay_id'), '?')}",
            _km(t["distance_meters"]),
            t["fix_count"],
        )
        for t in payload["trips"]
    ]
    click.secho("\nTrips", bold=True)
    _render_table(("FROM", "TO", "LENGTH", "ROUTE", "DISTANCE", "FIXES"), "<<<<<>", rows)


def _print_gaps(payload: dict) -> None:
    for g in payload["gaps"]:
        start, end = _hhmm(g["start_local"], g["start_at"]), _hhmm(g["end_local"], g["end_at"])
        click.echo(f"  No sightings between {start} and {end} ({_mins(g['minutes'])}).")


def _print_table(payload: dict) -> None:
    click.echo(f"{payload['device_id']}  {payload['date']}  ({payload['timezone']})")
    if not payload["fix_count"]:
        click.echo("No sightings in this range.")
    else:
        _print_stays(payload)
        _print_trips(payload)
        if payload["gaps"]:
            click.secho("\nGaps", bold=True)
            _print_gaps(payload)
        if payload["outliers"]:
            click.echo(
                f"\n{len(payload['outliers'])} stray fix(es) left out of trips (still stored)."
            )
    click.echo(f"\n{honesty.TRIPS_APPROXIMATE}")


@click.command("trips")
@click.option("--device-id", default=None, help="Device to show. Optional when one is tracked.")
@click.option("--date", "day", default=None, help="Local date, YYYY-MM-DD. Default today.")
@click.option("--days", default=1, type=click.IntRange(1, 31), help="Number of days from --date.")
@click.option("--timezone", default=None, help="IANA zone. Default this computer's.")
@click.option("--json", "as_json", is_flag=True, help="Print the API payload as JSON.")
def trips_cmd(
    device_id: str | None, day: str | None, days: int, timezone: str | None, as_json: bool
):
    """Show stays, trips and gaps for one device. Distances are approximate."""
    _prep()
    from findplus.timeline import local_zone
    from findplus.trips.service import trips_for

    zone = local_zone(timezone)
    try:
        start = date.fromisoformat(day) if day else datetime.now(zone).date()
    except ValueError as exc:
        raise click.BadParameter("expected YYYY-MM-DD", param_hint="--date") from exc
    with session_scope() as session:
        payload = trips_for(session, _pick_device(session, device_id), start, days, zone)
    if as_json:
        click.echo(json.dumps(payload, indent=2))
    else:
        _print_table(payload)
    sys.stdout.flush()

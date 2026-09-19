"""History commands: export, prune.

Purpose    : Export stored observations to a file/stdout, and delete history
             before a cutoff date.
Inputs     : Export format/range options; a prune cutoff date and --yes flag.
Outputs    : Exported file/text, or a deletion count.
Constraints: prune is a dry run unless --yes is given; a second confirmation
             prompt guards the actual delete.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import click

from findplus.db.session import session_scope

from ._fmt import _prep


def _export_range(all_history: bool, day, start, end, tz):
    """`(start_utc, end_utc, label)` from the mutually exclusive range options."""
    from findplus.timeline import day_bounds_utc

    if all_history:
        return datetime(1970, 1, 1, tzinfo=UTC), datetime.now(UTC) + timedelta(days=1), "all"
    if day:
        target = date.fromisoformat(day)
        s_utc, e_utc = day_bounds_utc(target, tz)
        return s_utc, e_utc, target.isoformat()
    if start or end:
        s_date = date.fromisoformat(start) if start else date(1970, 1, 1)
        e_date = date.fromisoformat(end) if end else datetime.now(tz).date()
        s_utc, _ = day_bounds_utc(s_date, tz)
        _, e_utc = day_bounds_utc(e_date, tz)
        return s_utc, e_utc, f"{s_date}_to_{e_date}"
    target = datetime.now(tz).date()
    s_utc, e_utc = day_bounds_utc(target, tz)
    return s_utc, e_utc, target.isoformat()


def _export_body(fmt: str, device_id, group_id, start_utc, end_utc, tz, label: str):
    """`(body, count)` — the group branch counts rendered lines, not observations."""
    from findplus.exporters import export as render
    from findplus.group_export import GroupNotFoundError, export_group
    from findplus.timeline import fetch_observations

    if group_id is not None:
        with session_scope() as session:
            try:
                body, _slug = export_group(session, group_id, fmt, start_utc, end_utc, tz)
            except GroupNotFoundError:
                click.echo("Error: group not found", err=True)
                sys.exit(1)
        return body, body.count("\n")
    with session_scope() as session:
        rows = fetch_observations(session, device_id, start_utc, end_utc)
        return render(fmt, rows, tz, name=f"Bike history {label}"), len(rows)


@click.command()
@click.option("--format", "fmt", type=click.Choice(["csv", "json", "gpx", "kml"]), default="csv")
@click.option("--day", default=None, help="Single local day, YYYY-MM-DD.")
@click.option("--start", default=None, help="Range start, YYYY-MM-DD.")
@click.option("--end", default=None, help="Range end, YYYY-MM-DD.")
@click.option("--all", "all_history", is_flag=True, help="Export the entire history.")
@click.option("--device-id", default=None, help="Limit to one device. Omit for all devices.")
@click.option(
    "--group",
    "group_id",
    default=None,
    metavar="ID",
    help="Export every member's track (never merged).",
)
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def export(
    fmt: str,
    day: str | None,
    start: str | None,
    end: str | None,
    all_history: bool,
    device_id: str | None,
    group_id: str | None,
    output: Path | None,
) -> None:
    """Export history to CSV, JSON, GPX or KML."""
    _prep()
    from findplus.timeline import local_zone

    tz = local_zone()
    start_utc, end_utc, label = _export_range(all_history, day, start, end, tz)
    body, count = _export_body(fmt, device_id, group_id, start_utc, end_utc, tz, label)

    if output:
        output.write_text(body, encoding="utf-8")
        click.secho(f"Wrote {count} observation(s) to {output}", fg="green")
    else:
        click.echo(body)


@click.command("prune")
@click.option("--before", required=True, help="Delete observations before this local date.")
@click.option("--yes", is_flag=True, help="Actually delete. Without this it is a dry run.")
def prune(before: str, yes: bool) -> None:
    """Delete history before a date. Dry run unless --yes is given."""
    _prep()
    from sqlalchemy import func
    from sqlalchemy import select as sa_select

    from findplus.db.models import LocationObservation
    from findplus.timeline import day_bounds_utc, local_zone

    tz = local_zone()
    cutoff_utc, _ = day_bounds_utc(date.fromisoformat(before), tz)

    with session_scope() as session:
        count = (
            session.scalar(
                sa_select(func.count(LocationObservation.id)).where(
                    LocationObservation.observed_at < cutoff_utc
                )
            )
            or 0
        )
        if not yes:
            click.secho(f"Dry run: {count} observation(s) are older than {before}.", fg="yellow")
            click.echo("Re-run with --yes to delete them. History is never deleted silently.")
            return
        if not click.confirm(f"Permanently delete {count} observation(s) before {before}?"):
            raise click.Abort
        session.query(LocationObservation).filter(
            LocationObservation.observed_at < cutoff_utc
        ).delete(synchronize_session=False)
    click.secho(f"Deleted {count} observation(s).", fg="green")

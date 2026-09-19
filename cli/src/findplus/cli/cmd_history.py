"""History commands: export, prune.

Purpose    : Export stored observations to a file/stdout, and delete history
             before a cutoff date.
Inputs     : Export format/range options; a prune cutoff date and --yes flag.
Outputs    : Exported file/text, or a deletion count.
Constraints: prune is a dry run unless --yes is given; a second confirmation
             prompt guards the actual delete.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import click

from findplus.db.session import session_scope

from ._fmt import _prep


@click.command()
@click.option("--format", "fmt", type=click.Choice(["csv", "json", "gpx", "kml"]), default="csv")
@click.option("--day", default=None, help="Single local day, YYYY-MM-DD.")
@click.option("--start", default=None, help="Range start, YYYY-MM-DD.")
@click.option("--end", default=None, help="Range end, YYYY-MM-DD.")
@click.option("--all", "all_history", is_flag=True, help="Export the entire history.")
@click.option("--device-id", default=None, help="Limit to one device. Omit for all devices.")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def export(
    fmt: str,
    day: str | None,
    start: str | None,
    end: str | None,
    all_history: bool,
    device_id: str | None,
    output: Path | None,
) -> None:
    """Export history to CSV, JSON, GPX or KML."""
    _prep()
    from findplus.exporters import export as render
    from findplus.timeline import day_bounds_utc, fetch_observations, local_zone

    tz = local_zone()
    if all_history:
        start_utc = datetime(1970, 1, 1, tzinfo=UTC)
        end_utc = datetime.now(UTC) + timedelta(days=1)
        label = "all"
    elif day:
        target = date.fromisoformat(day)
        start_utc, end_utc = day_bounds_utc(target, tz)
        label = target.isoformat()
    elif start or end:
        s = date.fromisoformat(start) if start else date(1970, 1, 1)
        e = date.fromisoformat(end) if end else datetime.now(tz).date()
        start_utc, _ = day_bounds_utc(s, tz)
        _, end_utc = day_bounds_utc(e, tz)
        label = f"{s}_to_{e}"
    else:
        target = datetime.now(tz).date()
        start_utc, end_utc = day_bounds_utc(target, tz)
        label = target.isoformat()

    with session_scope() as session:
        rows = fetch_observations(session, device_id, start_utc, end_utc)
        body = render(fmt, rows, tz, name=f"Bike history {label}")

    if output:
        output.write_text(body, encoding="utf-8")
        click.secho(f"Wrote {len(rows)} observation(s) to {output}", fg="green")
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

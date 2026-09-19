"""Device commands: list/track devices, run one poll immediately.

Purpose    : Manage which devices are tracked and trigger a manual poll.
Inputs     : --track/--track-all/--untrack/--default/--refresh options.
Outputs    : Device table and tracking summary; poll cycle results.
Constraints: `poll-now` is the only command here that queries Google.
"""

from __future__ import annotations

import sys

import click

from findplus.config import get_settings
from findplus.db.session import session_scope

from ._fmt import _prep


@click.command()
@click.option("--track", "track_ids", multiple=True, help="Track this device id (repeatable).")
@click.option(
    "--track-all", "track_all_flag", is_flag=True, help="Track every device on the account."
)
@click.option("--untrack", "untrack_ids", multiple=True, help="Stop tracking a device id.")
@click.option("--default", "default_id", default=None, help="Device the dashboard opens on.")
@click.option("--refresh/--no-refresh", default=True, help="Re-query Find Hub for the list.")
def devices(
    track_ids: tuple[str, ...],
    track_all_flag: bool,
    untrack_ids: tuple[str, ...],
    default_id: str | None,
    refresh: bool,
) -> None:
    """List every tracker Find+ knows about and choose which ones to track.

    The table covers all providers, because an Apple accessory that has
    reported once has a device row too. `--refresh` re-reads the Google Find
    Hub account only; Apple accessories are added with `findplus apple`.
    Any number of devices can be tracked at once. Tracking N devices costs N
    provider requests per poll cycle, so the effective request rate is shown.
    """
    _prep()
    from sqlalchemy import func
    from sqlalchemy import select as sa_select

    from findplus.db.models import Device, LocationObservation
    from findplus.findhub.client import FindHubClient
    from findplus.ingest import upsert_device
    from findplus.state import (
        get_tracked_devices,
        set_default_device,
        track_all,
        track_devices,
        untrack_devices,
    )

    mutating = bool(track_ids or track_all_flag or untrack_ids or default_id)

    # --track-all with an empty local table means the list was never fetched.
    # Refresh first rather than silently "tracking all 0 devices".
    if track_all_flag:
        from sqlalchemy import select as _sel

        with session_scope() as session:
            known = len(list(session.scalars(_sel(Device))))
        if known == 0:
            refresh = True
            mutating = False

    if refresh and not mutating:
        try:
            found = FindHubClient().list_devices()
        except Exception as exc:
            click.secho(f"Could not list devices: {exc}", fg="red")
            click.echo("If the session expired, run: findplus auth")
            sys.exit(1)
        with session_scope() as session:
            for d in found:
                upsert_device(session, d.device_id, d.name)

    if track_all_flag:
        mutating = True

    if mutating:
        with session_scope() as session:
            try:
                if track_all_flag:
                    tracked = track_all(session)
                    click.secho(f"Now tracking all {len(tracked)} device(s).", fg="green")
                elif track_ids:
                    tracked = track_devices(session, track_ids, exclusive=True)
                    click.secho(
                        f"Now tracking {len(tracked)}: " + ", ".join(d.name for d in tracked),
                        fg="green",
                    )
                if untrack_ids:
                    removed = untrack_devices(session, untrack_ids)
                    click.secho(f"Stopped tracking {removed} device(s).", fg="yellow")
                    click.echo("Their history is kept; they are simply no longer polled.")
                if default_id:
                    set_default_device(session, default_id)
                    click.echo(f"Dashboard will open on {default_id}.")
            except LookupError as exc:
                click.secho(str(exc), fg="red")
                sys.exit(1)

    settings = get_settings()
    with session_scope() as session:
        rows = list(session.scalars(sa_select(Device).order_by(Device.name)))
        tracked = get_tracked_devices(session)
        if not rows:
            click.echo("No devices found on this account.")
            return

        click.echo("")
        click.secho(f"{'':4} {'NAME':<30} {'OBS':>7}  DEVICE ID", bold=True)
        for d in rows:
            count = session.scalar(
                sa_select(func.count(LocationObservation.id)).where(
                    LocationObservation.device_id == d.device_id
                )
            )
            mark = click.style(" [x]", fg="green") if d.is_tracked else " [ ]"
            click.echo(f"{mark} {d.name:<30} {count or 0:>7}  {d.device_id}")
        click.echo("")

        interval = settings.effective_poll_interval_minutes
        if tracked:
            rate = len(tracked) * 60 / interval
            click.echo(f"Tracking {len(tracked)} of {len(rows)} device(s).")
            click.echo(
                f"That is about {rate:.0f} Google requests/hour "
                f"({len(tracked)} device(s) every {interval:g} min), polled sequentially."
            )
        else:
            click.echo("Nothing is being tracked yet. Choose what to poll:")
            click.echo("  findplus devices --track-all")
            click.echo("  findplus devices --track <ID> --track <ID>")


@click.command("poll-now")
def poll_now() -> None:
    """Run a single Find Hub poll immediately."""
    _prep()
    from findplus.poller import poll_once

    cycle = poll_once()
    for o in cycle.outcomes:
        colour = {"ok": "green", "no_location": "yellow"}.get(o.status, "red")
        label = o.device_name or "(no device)"
        click.secho(f"{label:<28} {o.status}", fg=colour, nl=False)
        click.echo(f"   returned: {o.received}  new: {o.inserted}  dup: {o.duplicates}")
        if o.error_message:
            click.secho(f"    {o.error_message}", fg="red")
    click.echo("")
    click.echo(
        f"{len(cycle.outcomes)} device(s) polled  |  "
        f"{cycle.inserted} new observation(s)  |  {cycle.duplicates} duplicate(s)"
    )
    sys.exit(0 if cycle.ok else 1)

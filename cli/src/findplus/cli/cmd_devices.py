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

from ._fmt import _plural, _prep, _print_device_table, _print_nothing_tracked_hint


def _devices_as_json(session, rows) -> str:
    """The rows the table shows, as JSON (cli-reference.md pins `--json` on this command).

    Same shape as the table: one object per device, newest field set kept flat so a
    shell pipeline can read it without walking a nested structure.
    """
    import json

    from findplus.state import observation_counts

    counts = observation_counts(session, [d.device_id for d in rows])
    out = []
    for d in rows:
        count = counts.get(d.device_id, 0)
        out.append(
            {
                "device_id": d.device_id,
                "name": d.name,
                "label": d.label,
                "provider": d.provider,
                "is_tracked": d.is_tracked,
                "observation_count": int(count or 0),
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
        )
    return json.dumps(out, indent=2)


def _bootstrap_refresh_needed(track_all_flag: bool) -> bool:
    """--track-all over an empty local table means the list was never fetched.

    The caller refreshes first rather than silently "tracking all 0 devices".
    """
    if not track_all_flag:
        return False
    from sqlalchemy import select

    from findplus.db.models import Device

    with session_scope() as session:
        known = len(list(session.scalars(select(Device))))
    return known == 0


def _refresh_device_rows() -> None:
    """Re-read the Google Find Hub account into the devices table."""
    from findplus.ingest import upsert_device
    from findplus.providers.google_findhub.client import FindHubClient

    try:
        found = FindHubClient().list_devices()
    except Exception as exc:
        click.secho(f"Could not list devices: {exc}", fg="red")
        click.echo("If the session expired, run: findplus auth")
        sys.exit(1)
    with session_scope() as session:
        for d in found:
            upsert_device(session, d.device_id, d.name)


def _apply_mutations(
    track_ids: tuple[str, ...],
    track_all_flag: bool,
    untrack_ids: tuple[str, ...],
    default_id: str | None,
) -> None:
    """Apply --track/--track-all/--untrack/--default, one session for all."""
    from findplus.state import set_default_device, track_all, track_devices, untrack_devices

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


def _print_rate_or_hint(settings, tracked_count: int, total: int) -> None:
    """The request-rate line, or the nothing-tracked hint (cli-reference.md)."""
    interval = settings.effective_poll_interval_minutes
    if tracked_count:
        rate = tracked_count * 60 / interval
        # UAT4 N43: "device(s)" never resolved a real count -- proper
        # plurals for both the total and the tracked count in this line.
        click.echo(f"Tracking {tracked_count} of {total} {_plural(total, 'device')}.")
        # GP-R5-4: this line used to say "Google requests/hour" unconditionally,
        # which is wrong once an Apple Find My device is tracked alongside (or
        # instead of) a Google one -- "provider" covers whichever accounts are
        # actually configured, the same neutral wording catalog-en.js's
        # rateTracked/trackedResult strings already use for this dialog.
        click.echo(
            f"That is about {rate:.0f} provider requests/hour "
            f"({tracked_count} {_plural(tracked_count, 'device')} every {interval:g} min),"
            " polled sequentially."
        )
    else:
        _print_nothing_tracked_hint()


def _print_listing(json_out: bool) -> None:
    """The devices table (or --json), tracked count and request rate."""
    from sqlalchemy import select

    from findplus.db.models import Device
    from findplus.state import get_tracked_devices

    settings = get_settings()
    with session_scope() as session:
        rows = list(session.scalars(select(Device).order_by(Device.name)))
        tracked = get_tracked_devices(session)

        if json_out:
            click.echo(_devices_as_json(session, rows))
            return

        if not rows:
            click.echo("No devices known yet.")
            click.echo("Sign in with `findplus auth`, then `findplus devices --refresh`.")
            return

        _print_device_table(session)
        _print_rate_or_hint(settings, len(tracked), len(rows))


@click.group(name="devices", invoke_without_command=True)
@click.option("--track", "track_ids", multiple=True, help="Track this device id (repeatable).")
@click.option(
    "--track-all", "track_all_flag", is_flag=True, help="Track every device on the account."
)
@click.option("--untrack", "untrack_ids", multiple=True, help="Stop tracking a device id.")
@click.option("--default", "default_id", default=None, help="Device the dashboard opens on.")
@click.option(
    "--refresh/--no-refresh",
    default=False,
    help="Re-query Find Hub for the list before printing it (needs a signed-in account).",
)
@click.option("--json", "json_out", is_flag=True, help="Print the device list as JSON.")
@click.pass_context
def devices(
    ctx: click.Context,
    track_ids: tuple[str, ...],
    track_all_flag: bool,
    untrack_ids: tuple[str, ...],
    default_id: str | None,
    refresh: bool,
    json_out: bool,
) -> None:
    """List the trackers Find+ knows about and choose which ones to track.

    Lists from the local database by default, so it works without a signed-in
    account or a network call. Pass `--refresh` to re-read the Google Find
    Hub account first; Apple accessories are added with `findplus apple`. The
    table covers every provider, because an Apple accessory that has reported
    once has a device row too. Any number of devices can be tracked at once;
    tracking N devices costs N provider requests per poll cycle, so the
    effective request rate is shown.
    """
    if ctx.invoked_subcommand is not None:
        return
    _prep()

    mutating = bool(track_ids or track_all_flag or untrack_ids or default_id)
    if _bootstrap_refresh_needed(track_all_flag):
        refresh = True
        mutating = False

    if refresh and not mutating:
        _refresh_device_rows()

    if track_all_flag:
        mutating = True

    if mutating:
        _apply_mutations(track_ids, track_all_flag, untrack_ids, default_id)

    _print_listing(json_out)


@devices.command("label")
@click.argument("device_id")
@click.option("--label", "label_value", default=None, help="Your own name for this tracker.")
@click.option("--icon", "icon_value", default=None, help="lucide:<name>, letter:<X>, letter, none.")
@click.option("--color", "color_value", default=None, help="Lowercase #rrggbb.")
def label_device_cmd(device_id, label_value, icon_value, color_value):
    """Set a device's label, icon and/or color."""
    if label_value is None and icon_value is None and color_value is None:
        click.echo("Error: give at least one of --label, --icon, --color", err=True)
        sys.exit(2)
    from findplus.db.models import Device
    from findplus.labels import validate_color, validate_icon, validate_label

    with session_scope() as session:
        device = session.get(Device, device_id)
        if device is None:
            click.echo(f"Error: device {device_id} not found", err=True)
            sys.exit(1)
        try:
            # Validate every option before writing any of them: a bad --color
            # after a good --label must not leave the label half-applied.
            new_label = validate_label(label_value) if label_value is not None else None
            new_icon = validate_icon(icon_value) if icon_value is not None else None
            new_color = validate_color(color_value) if color_value is not None else None
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        if label_value is not None:
            device.label = new_label
        if new_icon is not None:
            device.icon = new_icon
        if new_color is not None:
            device.color = new_color
        session.flush()
        label_out, icon_out, color_out = device.label, device.icon, device.color
    click.echo(f"label={label_out!r} icon={icon_out!r} color={color_out!r}")


@devices.command("icons")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def icons_cmd(as_json):
    """List the available Lucide icon ids."""
    import json as _json

    from findplus.labels import lucide_subset

    rows = lucide_subset()
    if as_json:
        click.echo(_json.dumps(rows, indent=2))
        return
    click.echo(f"{'ID':<24}{'GROUP':<10}")
    for row in rows:
        click.echo(f"{row['id']:<24}{row['group']:<10}")

"""The `poll-now` command: one immediate provider poll, printed as a table.

Purpose    : Trigger and display a single poll cycle outside the schedule.
Inputs     : --device-id (repeatable) to narrow the poll.
Outputs    : Per-device outcome lines and a summary; exit code per spec.
Constraints: Split out of cmd_devices.py at the E2-CF-P2-14 file-cap split
             (the command was never a `devices` subcommand — it registers at
             the top level in main.py, so moving it changes no CLI surface).
             The only command here that queries Google, like `devices
             --refresh`; never run by the tests against a real account.
"""

from __future__ import annotations

import sys

import click

from ._fmt import _prep

#: poll-now exit codes, pinned in specs/cli-reference.md § poll-now.
_POLL_NOW_OK = 0
_POLL_NOW_FAILURE = 1
_POLL_NOW_UNAUTHENTICATED = 4
_POLL_NOW_NOTHING_TRACKED = 5

#: PollOutcome statuses that mean "the provider needs `findplus auth` again."
_UNAUTHENTICATED_STATUSES = {"auth_error", "provider_unauthenticated"}


def _poll_now_exit_code(cycle) -> int:
    """Map a poll cycle to the pinned poll-now exit codes.

    Checked in this order because a single cycle can only report one code:
    "nothing tracked" and "unauthenticated" are both failures a plain
    `cycle.ok` cannot distinguish from a generic one, so they are read off
    the outcomes' status/error_type directly, ahead of the ok/fail fallback.
    """
    error_types = {o.error_type for o in cycle.outcomes if o.error_type}
    if "NoDeviceTracked" in error_types:
        return _POLL_NOW_NOTHING_TRACKED
    statuses = {o.status for o in cycle.outcomes}
    if error_types & {"AuthRequiredError"} or statuses & _UNAUTHENTICATED_STATUSES:
        return _POLL_NOW_UNAUTHENTICATED
    return _POLL_NOW_OK if cycle.ok else _POLL_NOW_FAILURE


@click.command("poll-now")
@click.option(
    "--device-id",
    "device_ids",
    multiple=True,
    help="Poll only this device id (repeatable). Default: every tracked device.",
)
def poll_now(device_ids: tuple[str, ...]) -> None:
    """Run a single Find Hub poll immediately."""
    _prep()
    from findplus.poller import poll_once

    cycle = poll_once(device_ids=set(device_ids) if device_ids else None)
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
    sys.exit(_poll_now_exit_code(cycle))

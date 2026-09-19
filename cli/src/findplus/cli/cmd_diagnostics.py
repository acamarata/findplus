"""Diagnostics and install commands: watchdog, theme, PIN reset, install-watchdog.

Purpose    : The watchdog health check, watchdog-job install, and small
             settings-adjacent utilities. The `doctor` command moved to
             cli/doctor.py (P1-E7-W3-S1-T4, 10 pure checks + --repair/--json);
             `install-service` moved to being a named alias of `start` in
             main.py (P1-E7-W3-S1-T7) since it needed the same --program
             option — neither is implemented in this module any more.
Inputs     : Mostly --yes confirmation skips; theme takes a required argument.
Outputs    : Console diagnostic tables; installed watchdog units.
Constraints: Split out of cmd_service.py (which was 398 lines, over the
             300-line/file hard rule).
"""

from __future__ import annotations

import click

from findplus.config import get_settings
from findplus.db.session import session_scope
from findplus.logging_setup import configure_logging

from ._fmt import _prep, _show_service_plan


@click.command()
def watchdog() -> None:
    """Check the local API and restart the service if it is not answering.

    Run periodically by the watchdog job. `KeepAlive` already covers a crashed
    process; this covers a process that is alive but wedged. The probe and
    port-mismatch logic live in service/watchdog.py (specs/service-package.md)
    — this command is a thin caller.
    """
    from findplus import service

    settings = get_settings()
    configure_logging(settings, to_file=True, console=False)
    click.echo(f"watchdog: {service.restart_if_wedged(settings)}")


@click.command("install-watchdog")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def install_watchdog_cmd(yes: bool) -> None:
    """Show, then optionally install, the watchdog job."""
    _prep()
    from findplus import service

    p = service.watchdog_plan()
    _show_service_plan(p)
    click.echo(
        f"It runs every {service.WATCHDOG_INTERVAL_SECONDS // 60} minutes, asks the local\n"
        "API whether it is alive, and restarts the service only if it is not.\n"
    )
    if not yes and not click.confirm("Install this now?", default=False):
        click.echo("Nothing was changed.")
        return
    service.install_watchdog(confirmed=True)
    click.secho("Watchdog installed and started.", fg="green")


@click.command("reset-lock")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def reset_lock(yes: bool) -> None:
    """Forgot your PIN? Remove the app lock from this machine.

    There is no cloud reset for the PIN, by design. Anyone who can run this
    command already has access to the database file, so this recovery path adds
    no exposure that did not already exist.
    """
    _prep()
    from findplus.appsettings import clear_pin, load_settings

    with session_scope() as session:
        current = load_settings(session)
        if not current.pin_configured:
            click.echo("No PIN is set; nothing to reset.")
            return
        if not yes and not click.confirm(
            "Remove the app-lock PIN? The dashboard will open without one.", default=False
        ):
            raise click.Abort
        clear_pin(session)

    click.secho("App lock removed. Set a new PIN from Settings in the dashboard.", fg="green")
    click.echo("Restart the service so running sessions pick this up: findplus start")


@click.command()
@click.argument("theme", type=click.Choice(["dark", "light", "system"]))
def theme(theme: str) -> None:
    """Set the dashboard theme without opening the UI."""
    _prep()
    from findplus.appsettings import save_theme

    with session_scope() as session:
        save_theme(session, theme)
    click.secho(f"Theme set to {theme}.", fg="green")

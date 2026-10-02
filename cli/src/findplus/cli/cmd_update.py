"""`findplus update` command group: see and steer automatic updates.

Purpose    : Show where the update stands, check now, switch automatic updates
             on or off, and (for developers) point the updater at a folder of
             local builds.
Inputs     : `status`; `check`; `auto on|off`; `dev-dir [PATH] [--clear]`.
Outputs    : Console lines; settings-table rows `updates.auto`, `updates.dev_dir`.
Constraints: Installing is the desktop app's job (it quits, swaps and restarts
             itself), so there is no install command here. `check` downloads only
             inside the macOS app; from the CLI it reports what it found.
"""

from __future__ import annotations

from pathlib import Path

import click

from findplus.config import get_settings
from findplus.db.session import session_scope
from findplus.updater import devsource, prefs
from findplus.updater.check import check
from findplus.updater.status import can_install_here, status

from ._fmt import _prep


@click.group(name="update")
def update_cmd() -> None:
    """Automatic updates: status, check now, on/off, developer builds."""


def _print(body: dict) -> None:
    click.echo(f"installed     {body['current_version']}")
    click.echo(f"automatic     {'on' if body['auto'] else 'off'}")
    click.echo(f"last check    {body['checked_at'] or 'never'}")
    click.echo(f"newest        {body['latest_version'] or 'unknown'}")
    click.echo(f"ready         {body['staged_version'] or 'nothing staged'}")
    if body["error"]:
        click.echo(f"problem       {body['error']}")
    if body["last_attempt_failed"]:
        click.echo("last install  did not finish; the app is still on the old version")


@update_cmd.command("status")
def update_status() -> None:
    """Show the installed version and what the updater has found."""
    _prep()
    with session_scope() as session:
        auto = prefs.auto_enabled(session)
    _print(status(get_settings().state_dir, auto=auto))


@update_cmd.command("check")
def update_check() -> None:
    """Ask GitHub for the newest release now (one request, nothing about you is sent)."""
    _prep()
    with session_scope() as session:
        dev_dir = devsource.dev_dir(session)
        auto = prefs.auto_enabled(session)
    state_dir = get_settings().state_dir
    check(state_dir, download=can_install_here(), dev_dir=dev_dir)
    _print(status(state_dir, auto=auto))


@update_cmd.command("auto")
@click.argument("state", type=click.Choice(["on", "off"]))
def update_auto(state: str) -> None:
    """Turn automatic updates on or off. Off: no update request unless you ask."""
    _prep()
    with session_scope() as session:
        prefs.set_auto(session, state == "on")
    click.echo(f"updates.auto = {state}")


@update_cmd.command("dev-dir")
@click.argument("path", required=False, type=click.Path(file_okay=False, path_type=Path))
@click.option("--clear", is_flag=True, help="Stop using a developer build folder.")
def update_dev_dir(path: Path | None, clear: bool) -> None:
    """For developers: install local builds of Find+.app from PATH automatically."""
    _prep()
    with session_scope() as session:
        if clear:
            devsource.set_dev_dir(session, None)
        elif path is not None:
            try:
                devsource.set_dev_dir(session, str(path.expanduser().resolve()))
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
        current = devsource.dev_dir(session)
    click.echo(f"updates.dev_dir = {current or '(off)'}")

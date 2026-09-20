"""`findplus widget` command group: macOS WidgetKit widget controls.

Purpose    : Toggle the widget's map preview and trigger a WidgetKit
             timeline reload from the command line.
Inputs     : `show-map on|off`; `refresh` (no arguments).
Outputs    : Writes the settings-table key `widget.show_map`; shells out to
             `open findplus://refresh-widget`.
Constraints: PATCH /api/settings carries a pinned body (api-contract.md, and
             service-and-settings.md § 4 for the P2 additions) and silently
             drops unknown body fields, `widget.show_map` among them,
             so show-map writes the settings table directly, the same
             pattern cmd_diagnostics.theme uses for save_theme. refresh
             never execs the reload-widgets binary itself — it only opens
             the findplus:// URL scheme the Tauri app already handles.
"""

from __future__ import annotations

import subprocess

import click

from findplus.db.session import session_scope
from findplus.state import set_setting

from ._fmt import _prep


@click.group(name="widget")
def widget() -> None:
    """Widget management commands."""


@widget.command("show-map")
@click.argument("state", type=click.Choice(["on", "off"]))
def show_map(state: str) -> None:
    """Show or hide the map preview in the large widget.

    The map preview sends the coordinate region to Apple Maps.
    """
    _prep()
    value = "1" if state == "on" else "0"
    with session_scope() as session:
        set_setting(session, "widget.show_map", value)
    click.echo(f"widget.show_map = {value}")


@widget.command("refresh")
def refresh() -> None:
    """Ask the Find+ app to reload the widget's WidgetKit timelines."""
    result = subprocess.run(["open", "findplus://refresh-widget"], capture_output=True)
    if result.returncode != 0:
        click.echo("app not installed")
        raise SystemExit(1)

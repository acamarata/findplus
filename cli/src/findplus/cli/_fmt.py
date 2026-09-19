"""Private formatting/prep helpers shared by the cli/ command modules.

Purpose    : Small, repeated console-output helpers and the pre-command setup
             routine (logging, dirs, migrations) every mutating command runs.
Inputs     : Plain strings/booleans for the formatters; an optional to_file
             flag for _prep.
Outputs    : Printed lines (via click.echo/secho); _prep has no return value.
Constraints: No command logic here — pure helpers only, so each cmd_* module
             imports exactly what it needs.
"""

from __future__ import annotations

import click

from findplus.config import get_settings
from findplus.db.migrate import upgrade_to_head
from findplus.logging_setup import configure_logging


def _prep(to_file: bool = False) -> None:
    settings = get_settings()
    configure_logging(settings, to_file=to_file)
    settings.ensure_dirs()
    upgrade_to_head()


def _show_service_plan(p) -> None:
    click.echo("")
    click.secho("This is exactly what will be installed:", bold=True)
    _row("platform", p.platform)
    _row("manager", p.manager)
    _row("file", str(p.unit_path))
    _row("load", " ".join(p.load_command))
    click.echo("\n--- file contents ---")
    click.echo(p.unit_text.strip())
    click.echo("--- end ---")
    click.echo("\nUser-level only. No sudo, nothing written outside your home directory.\n")


def _row(label: str, value: str) -> None:
    click.echo(f"  {label:<20} {value}")


def _check(label: str, ok: bool, detail: str) -> None:
    mark = click.style("ok  ", fg="green") if ok else click.style("FAIL", fg="red")
    click.echo(f"  [{mark}] {label:<32} {detail}")

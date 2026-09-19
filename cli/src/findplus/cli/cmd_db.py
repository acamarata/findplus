"""`findplus db` command group: migration and inspection commands.

Purpose    : Explicit database control independent of the daemon's own
             auto-upgrade at startup — for scripts, post-install hooks,
             and the wheel smoke test.
Inputs     : none (all commands act on the configured Settings.database_path).
Outputs    : Console output; upgrade mutates the SQLite file on disk.
Constraints: Delegates to db/migrate.py; never runs raw SQL here.
"""

from __future__ import annotations

import click

from findplus.config import get_settings
from findplus.db.migrate import current_revision, run_migrations


@click.group("db")
def db_cmd() -> None:
    """Database migration and inspection commands."""


@db_cmd.command("upgrade")
def db_upgrade() -> None:
    """Run Alembic migrations to head. Safe to run repeatedly (idempotent)."""
    settings = get_settings()
    settings.ensure_state_dir()
    run_migrations(settings.database_url, "head")
    click.echo(f"Database upgraded to head: {settings.database_path}")


@db_cmd.command("current")
def db_current() -> None:
    """Print the current Alembic revision of the database."""
    rev = current_revision(get_settings().database_url)
    click.echo(rev or "(base — no migrations applied)")


@db_cmd.command("path")
def db_path() -> None:
    """Print the absolute path to the SQLite database file."""
    click.echo(str(get_settings().database_path))

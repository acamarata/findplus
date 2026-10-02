"""`findplus db` operations: backup, restore, check, recompute-quality, rebuild-derived, import.

Purpose    : The durability and maintenance commands that sit beside
             `db upgrade|current|path` (cmd_db.py registers them).
Inputs     : See each command's options. All act on the configured database.
Outputs    : Plain-words console output; `--json` where a script may want it.
Constraints: Restore refuses while the daemon runs (unless --force), always
             takes a pre-restore backup first, and never deletes the file it
             replaces. Backups never include secrets (they are database copies
             only). Nothing here talks to the network.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import click

from findplus.config import get_settings


def _echo_json(payload: object) -> None:
    click.echo(json.dumps(payload, indent=2, default=str))


@click.command("backup")
@click.option("--json", "as_json", is_flag=True, help="Print the result as JSON.")
def db_backup(as_json: bool) -> None:
    """Make a verified copy of the database now (kept until you delete it)."""
    from findplus.db.backup import BackupError, create_backup

    settings = get_settings()
    try:
        info = create_backup(settings.database_path, settings.effective_backup_dir, kind="manual")
    except BackupError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        _echo_json({"path": str(info.path), "size_bytes": info.size_bytes, "kind": info.kind})
    else:
        click.secho(f"Backup saved: {info.path} ({info.size_bytes // 1024} KB)", fg="green")


@click.command("backups")
@click.option("--json", "as_json", is_flag=True, help="Print the list as JSON.")
def db_backups(as_json: bool) -> None:
    """List the backups on disk, newest first."""
    from findplus.db.backup import list_backups

    settings = get_settings()
    rows = list_backups(settings.effective_backup_dir)
    if as_json:
        _echo_json(
            [
                {"path": str(b.path), "kind": b.kind, "taken_at": b.taken_at, "size": b.size_bytes}
                for b in rows
            ]
        )
        return
    if not rows:
        click.echo(f"No backups yet in {settings.effective_backup_dir}.")
    for b in rows:
        click.echo(
            f"{b.taken_at:%Y-%m-%d %H:%M} UTC  {b.kind:<10} {b.size_bytes // 1024:>8} KB  {b.path}"
        )


@click.command("restore")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--force", is_flag=True, help="Restore even if Find+ looks like it is running.")
def db_restore(file: Path, force: bool) -> None:
    """Replace the database with a backup. Your current one is kept aside, not deleted."""
    from findplus.cli.cmd_serve import _check_exclusive
    from findplus.db.backup import BackupError
    from findplus.db.restore import RestoreError, restore_backup

    settings = get_settings()
    try:
        result = restore_backup(
            settings,
            file,
            daemon_running=lambda: _check_exclusive(settings.state_dir)[0],
            force=force,
        )
    except (RestoreError, BackupError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.secho(f"Restored from {result.restored_from.name}.", fg="green")
    if result.replaced_file:
        click.echo(f"Your previous database was kept as {result.replaced_file}")
    if result.pre_restore_backup:
        click.echo(f"A pre-restore backup is at {result.pre_restore_backup}")
    click.echo(f"Schema revision: {result.revision_after}")


@click.command("check")
@click.option("--json", "as_json", is_flag=True, help="Print the result as JSON.")
def db_check(as_json: bool) -> None:
    """Check the database for damage (quick, integrity and foreign-key checks)."""
    from findplus.db.integrity import check_database

    report = check_database(get_settings().database_path, full=True)
    if as_json:
        _echo_json({"ok": report.ok, "problems": report.problems})
    elif report.ok:
        click.secho("The database file is sound.", fg="green")
    else:
        click.secho("The database has problems:", fg="red")
        for line in report.problems:
            click.echo(f"  {line}")
        click.echo("Restore a backup with: findplus db restore <file>   (see findplus db backups)")
    sys.exit(0 if report.ok else 1)


@click.command("recompute-quality")
@click.option("--since", default=None, help="Only sightings from this local date, YYYY-MM-DD.")
def db_recompute_quality(since: str | None) -> None:
    """Re-score every sighting for 'looks wrong' flags (raw data is never changed)."""
    from findplus.db.session import session_scope
    from findplus.quality.store import recompute
    from findplus.timeline import day_bounds_utc, local_zone

    from ._fmt import _prep

    _prep(writes=True)
    start = day_bounds_utc(date.fromisoformat(since), local_zone())[0] if since else None
    with session_scope() as session:
        result = recompute(session, since=start, commit_every=2000)
    click.echo(
        f"Scored {result.rows} sighting(s) across {result.devices} tracker(s); "
        f"{result.suspects} look wrong."
    )


@click.command("rebuild-derived")
@click.option("--force", is_flag=True, help="Run even if Find+ looks like it is running.")
def db_rebuild_derived(force: bool) -> None:
    """Rebuild place, group and person state from the sightings (run it after an import).

    Replays every sighting, oldest first, and marks every rebuilt event as already
    notified, so nothing is sent about the past. Dismissed left-behind notes are lost.
    """
    from findplus.cli.cmd_serve import _check_exclusive
    from findplus.db.rebuild import rebuild_derived
    from findplus.db.session import session_scope

    from ._fmt import _prep

    _prep(writes=True)
    settings = get_settings()
    if _check_exclusive(settings.state_dir)[0] and not force:
        raise click.ClickException(
            "Find+ is running. Stop it first (findplus stop), or pass --force."
        )
    with session_scope() as session:
        result = rebuild_derived(session, settings)
    click.secho(
        f"Replayed {result.observations} sighting(s): {result.place_events} place event(s), "
        f"{result.group_events} group/person event(s), {result.left_behind} left-behind note(s). "
        "Nothing was sent.",
        fg="green",
    )


@click.command("import")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def db_import(file: Path) -> None:
    """Load a full export (`findplus export --format jsonl`) into an empty database."""
    from findplus.db.portable_import import PortableImportError, import_lines
    from findplus.db.session import session_scope

    from ._fmt import _prep

    _prep(writes=True)
    try:
        with session_scope() as session, file.open(encoding="utf-8") as fh:
            result = import_lines(session, fh)
    except PortableImportError as exc:
        raise click.ClickException(str(exc)) from exc
    parts = ", ".join(f"{n} {kind}" for kind, n in result.counts.items())
    click.secho(f"Imported: {parts}.", fg="green")
    click.echo("Next run `findplus db recompute-quality`, then `findplus db rebuild-derived`.")


COMMANDS = (
    db_backup,
    db_backups,
    db_restore,
    db_check,
    db_recompute_quality,
    db_rebuild_derived,
    db_import,
)

"""Restore the database from a backup, safely.

Purpose    : `findplus db restore <file>`: replace the live database with a
             backup without ever making things worse.
Inputs     : Settings, a backup file, and a callable saying whether the daemon
             is running (the CLI passes the same probe `serve` uses).
Outputs    : `RestoreResult`; the database file now holds the backup, upgraded
             to the current schema.
Constraints: Order matters, and every step is reversible until the last:
             1. validate the file (SQLite header, `quick_check`, a known schema
                revision, not newer than this Find+);
             2. refuse while the daemon runs unless `force`;
             3. take a pre-restore backup of the current database;
             4. build the new file beside the old one, verify it;
             5. move the current file aside as `findplus.sqlite.replaced-<stamp>`
                (never deleted), drop its stale -wal/-shm, move the new file in;
             6. upgrade to head.
             The file the owner passes is only ever read.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic.script import ScriptDirectory

from findplus.db import backup
from findplus.db.integrity import check_database, open_readonly
from findplus.db.migrate import _config, upgrade_to_head


class RestoreError(RuntimeError):
    """Restore refused or failed. The message is plain words; nothing was changed
    unless the message says otherwise."""


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """What a restore did."""

    restored_from: Path
    replaced_file: Path | None
    pre_restore_backup: Path | None
    revision_before: str | None
    revision_after: str


def backup_revision(path: Path) -> str | None:
    """The schema revision recorded in a database file, or None when it has none."""
    conn = open_readonly(path)
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return row[0] if row else None


def validate_backup(path: Path) -> str:
    """Raise RestoreError unless `path` is a sound Find+ database; return its revision."""
    if not path.is_file():
        raise RestoreError(f"{path} is not a file.")
    with path.open("rb") as fh:
        if fh.read(16) != b"SQLite format 3\x00":
            raise RestoreError(f"{path.name} is not a SQLite database file.")
    report = check_database(path)
    if not report.ok:
        raise RestoreError(f"{path.name} did not pass its check: " + "; ".join(report.problems))
    revision = backup_revision(path)
    if revision is None:
        raise RestoreError(f"{path.name} is not a Find+ database (it has no schema version).")
    try:
        ScriptDirectory.from_config(_config()).get_revision(revision)
    except Exception as exc:
        raise RestoreError(
            f"{path.name} was made by a newer Find+ (schema {revision}). Update Find+ first."
        ) from exc
    return revision


def _checkpoint(database: Path) -> None:
    """Fold the live WAL into the main file so moving the file aside loses nothing."""
    conn = sqlite3.connect(database, timeout=10)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _swap_in(new_file: Path, database: Path, now: datetime) -> Path | None:
    """Move the live file aside, remove its sidecars, move `new_file` into place."""
    replaced: Path | None = None
    if database.exists():
        replaced = database.with_name(f"{database.name}.replaced-{now.strftime('%Y%m%d-%H%M%S')}")
        os.replace(database, replaced)
    for suffix in ("-wal", "-shm"):
        Path(f"{database}{suffix}").unlink(missing_ok=True)
    os.replace(new_file, database)
    if os.name != "nt":
        database.chmod(0o600)
    return replaced


def restore_backup(
    settings,
    source: Path,
    *,
    daemon_running: Callable[[], bool] = lambda: False,
    force: bool = False,
    now: datetime | None = None,
) -> RestoreResult:
    """Replace the live database with `source` (see the module docstring for the order)."""
    now = now or datetime.now(UTC)
    validate_backup(source)
    if daemon_running() and not force:
        raise RestoreError(
            "Find+ is running. Stop it first (findplus stop), or pass --force "
            "if you are sure nothing is writing."
        )
    database: Path = settings.database_path
    before = backup_revision(database) if database.exists() else None
    pre: Path | None = None
    if database.exists():
        _checkpoint(database)
        pre = backup.create_backup(
            database, settings.effective_backup_dir, kind="prerestore", now=now
        ).path
    staged = database.with_name(f".restore-{now.strftime('%Y%m%d-%H%M%S')}.sqlite")
    try:
        backup.snapshot(source, staged)
        if not check_database(staged).ok:
            raise RestoreError("The copy did not verify. Nothing was changed.")
        _forget_engine(settings)
        replaced = _swap_in(staged, database, now)
    finally:
        staged.unlink(missing_ok=True)
    _forget_engine(settings)
    after = upgrade_to_head(settings.database_url)
    return RestoreResult(source, replaced, pre, before, after)


def _forget_engine(settings) -> None:
    """Drop pooled connections to the old file so the next query opens the restored one."""
    from findplus.db.session import get_engine

    get_engine(settings.database_url).dispose()
    get_engine.cache_clear()

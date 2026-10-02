"""A verified backup before a schema upgrade, so a new version can never cost history.

Purpose    : The first start of a new Find+ version upgrades the database schema.
             Before that happens, take a `preupdate` backup (db/backup.py) of the
             database exactly as the old version left it.
Inputs     : Settings (database path, backup directory).
Outputs    : The backup's path, or None when there was nothing to upgrade.
Constraints: Runs only when the database exists, already has a schema, and is
             behind the newest migration: a fresh install and an up-to-date one
             take no backup. A failed backup is logged and never stops the
             upgrade: an app update already took its own backup moments before,
             and refusing to upgrade would leave new code on an old schema.
"""

from __future__ import annotations

from pathlib import Path

from findplus.logging_setup import get_logger

log = get_logger(__name__)


def backup_before_migrate(settings) -> Path | None:
    """Back up the database when a schema upgrade is about to run. Never raises."""
    from findplus.db.backup import create_backup
    from findplus.db.migrate import current_revision, head_revision

    if not settings.database_path.exists():
        return None
    try:
        current = current_revision(settings.database_url)
        if current is None or current == head_revision():
            return None
        info = create_backup(
            settings.database_path, settings.effective_backup_dir, kind="preupdate"
        )
    except Exception as exc:  # logged, never fatal (see Constraints)
        log.warning("premigrate_backup_failed", error=str(exc))
        return None
    log.info("premigrate_backup", path=str(info.path), from_revision=current)
    return info.path

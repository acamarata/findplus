"""Backup status and "Back up now" for the Settings dialog.

Purpose    : The Settings dialog shows when the last backup was taken and lets the
             owner take one now, with the same code `findplus db backup` runs.
Inputs     : Settings (database path, backup directory).
Outputs    : GET /api/settings/backup -> {directory, count, last_backup_at,
             last_kind, last_size_bytes}; POST /api/settings/backup/now -> the same
             body after a manual backup, or 500 with the plain-words reason.
Constraints: Gated by the lock like every /api/ path. A backup holds the database
             only: no sign-in tokens or keys, but the PIN hash is included
             (db/backup.py). Nothing here deletes a backup.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from findplus.config import get_settings
from findplus.db.backup import BackupError, create_backup, list_backups


def _status() -> dict[str, Any]:
    settings = get_settings()
    directory = settings.effective_backup_dir
    backups = list_backups(directory)
    newest = backups[0] if backups else None
    return {
        "directory": str(directory),
        "count": len(backups),
        "last_backup_at": newest.taken_at.isoformat() if newest else None,
        "last_kind": newest.kind if newest else None,
        "last_size_bytes": newest.size_bytes if newest else None,
    }


def get_backup_status() -> dict[str, Any]:
    return _status()


def post_backup_now() -> dict[str, Any]:
    settings = get_settings()
    try:
        create_backup(settings.database_path, settings.effective_backup_dir, kind="manual")
    except BackupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _status()


def register_backup_routes(router: APIRouter) -> None:
    router.add_api_route("/backup", get_backup_status, methods=["GET"])
    router.add_api_route("/backup/now", post_backup_now, methods=["POST"])

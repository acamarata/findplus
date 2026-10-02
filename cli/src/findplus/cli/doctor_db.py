"""Database health checks for `findplus doctor`.

Purpose    : Two more doctor checks, kept out of doctor.py (at its 300-line cap):
             `db_integrity` (quick, integrity and foreign-key checks on the
             history database) and `db_backups` (a recent backup exists, and the
             backup directory and files are private).
Inputs     : Settings (database path, backup directory).
Outputs    : DoctorCheck values; `repair_backup_perms` chmods and returns None.
Constraints: Read-only except the repair. A failed integrity check is never
             auto-repaired: the detail points at `findplus db restore`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from findplus.db.backup import list_backups
from findplus.db.integrity import check_database

from .doctor_perms import DoctorCheck

#: The newest automatic backup may be this old before the check fails.
STALE_AFTER = timedelta(days=3)


def check_db_integrity(settings) -> DoctorCheck:
    path = settings.database_path
    if not path.exists():
        return DoctorCheck("db_integrity", "Database integrity", True, "No database yet.")
    report = check_database(path, full=True)
    if report.ok:
        return DoctorCheck(
            "db_integrity", "Database integrity", True, "The database file is sound."
        )
    first = "; ".join(report.problems[:3])
    return DoctorCheck(
        "db_integrity",
        "Database integrity",
        False,
        f"The database has problems ({first}). Restore a backup: findplus db restore <file>.",
    )


def _bad_perms(settings) -> list[str]:
    directory = settings.effective_backup_dir
    if os.name == "nt" or not directory.is_dir():
        return []
    bad = [str(directory)] if directory.stat().st_mode & 0o077 else []
    bad += [b.path.name for b in list_backups(directory) if b.path.stat().st_mode & 0o077]
    return bad


def check_db_backups(settings, now: datetime | None = None) -> DoctorCheck:
    now = now or datetime.now(UTC)
    bad = _bad_perms(settings)
    if bad:
        return DoctorCheck(
            "db_backups",
            "Database backups",
            False,
            f"Backups are readable by other users ({bad[0]}). Run findplus doctor --repair.",
            repairable=True,
        )
    autos = [b for b in list_backups(settings.effective_backup_dir) if b.kind == "auto"]
    if not autos:
        return DoctorCheck(
            "db_backups", "Database backups", True, "No backup yet. The daemon makes one daily."
        )
    age = now - autos[0].taken_at
    if age > STALE_AFTER:
        return DoctorCheck(
            "db_backups",
            "Database backups",
            False,
            f"The newest backup is {age.days} days old. Run findplus db backup.",
        )
    return DoctorCheck(
        "db_backups",
        "Database backups",
        True,
        f"Latest backup {autos[0].taken_at:%Y-%m-%d %H:%M} UTC.",
    )


def repair_backup_perms(settings) -> None:
    """Make the backup directory 0700 and every backup file 0600."""
    directory = settings.effective_backup_dir
    if os.name == "nt" or not directory.is_dir():
        return
    directory.chmod(0o700)
    for b in list_backups(directory):
        b.path.chmod(0o600)


def db_checks(settings) -> list[DoctorCheck]:
    """The two checks, in doctor order."""
    return [check_db_integrity(settings), check_db_backups(settings)]

"""Online SQLite backups, verified and rotated, with no sign-in tokens or keys.

Purpose    : Keep recent copies of the history database so a bad disk, a bad
             upgrade or a mistaken delete costs hours, not months.
Inputs     : Settings (database path, backup directory, keep counts).
Outputs    : Backup files `findplus-<UTC stamp>.sqlite` (automatic, rotated),
             `findplus-manual-<stamp>.sqlite`, `findplus-prerestore-<stamp>.sqlite`
             and `findplus-preupdate-<stamp>.sqlite` (taken before an app update
             or a schema upgrade; never aged out), all mode 0600 in a 0700
             directory.
Constraints: Uses SQLite's online backup API (`Connection.backup`), a consistent
             snapshot while the daemon keeps writing; never a file copy of a live
             WAL database. Each copy is written under a temporary name, verified
             by opening it and running `quick_check`, and only then renamed into
             place. The backup contains the database only: `secrets.json`,
             `alerts.json` and Apple tokens live outside it and are never copied. The
             `settings` table is in it, and that holds the app-lock PIN hash and
             salt: no sign-in tokens or keys, but the PIN hash is included.
             Rotation keeps the newest automatic backup of each of the last N
             days plus the newest of each of the last K older weeks, and the
             newest KEEP_MANUAL manual, KEEP_PRERESTORE pre-restore and
             KEEP_PREUPDATE pre-update backups.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from findplus.db.integrity import check_database

#: A new automatic backup is due when the newest one is older than this.
DUE_AFTER = timedelta(hours=24)
#: Manual and pre-restore backups are never aged out, but only this many are kept.
KEEP_MANUAL = 10
KEEP_PRERESTORE = 5
KEEP_PREUPDATE = 5
_STAMP = "%Y%m%d-%H%M%S"
_AUTO = re.compile(r"^findplus-(\d{8}-\d{6})\.sqlite$")
_ALL = re.compile(r"^findplus-(?:(manual|prerestore|preupdate)-)?(\d{8}-\d{6})\.sqlite$")


class BackupError(RuntimeError):
    """A backup could not be made or did not verify. The message is plain words."""


@dataclass(frozen=True, slots=True)
class BackupInfo:
    """One backup file on disk."""

    path: Path
    kind: str  # auto | manual | prerestore | preupdate
    taken_at: datetime
    size_bytes: int


def prepare_dir(directory: Path) -> Path:
    """Create the backup directory at 0700 (and tighten it if it already exists).

    `Settings.effective_backup_dir` is always a Find+ owned folder, so a folder the
    owner chose (Documents, an external disk) never has its permissions changed.
    """
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            directory.chmod(0o700)
    except OSError as exc:
        raise BackupError(f"The backup folder {directory} cannot be used: {exc}") from exc
    return directory


def _target(directory: Path, kind: str, now: datetime) -> Path:
    prefix = "findplus-" if kind == "auto" else f"findplus-{kind}-"
    return directory / f"{prefix}{now.strftime(_STAMP)}.sqlite"


def snapshot(source: Path, dest: Path) -> None:
    """Copy `source` to `dest` with the online backup API (consistent, WAL-safe)."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            # A single self-contained file: no -wal/-shm beside the copy, and the live
            # database switches itself back to WAL on its next connection.
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
    finally:
        src.close()


def create_backup(
    database: Path, directory: Path, *, kind: str = "auto", now: datetime | None = None
) -> BackupInfo:
    """Snapshot `database` into `directory`, verify it, and return its description."""
    now = now or datetime.now(UTC)
    if not database.exists():
        raise BackupError("There is no database to back up yet.")
    prepare_dir(directory)
    final = _target(directory, kind, now)
    while final.exists():  # two backups in one second must not replace each other
        now += timedelta(seconds=1)
        final = _target(directory, kind, now)
    temp = final.with_name(f".partial-{final.name}")
    temp.unlink(missing_ok=True)
    try:
        snapshot(database, temp)
        if os.name != "nt":
            temp.chmod(0o600)
        report = check_database(temp)
        if not report.ok:
            raise BackupError(
                "The new backup did not pass its check: " + "; ".join(report.problems)
            )
        os.replace(temp, final)
    except sqlite3.Error as exc:
        raise BackupError(f"The backup could not be written: {exc}") from exc
    finally:
        for leftover in (temp, Path(f"{temp}-wal"), Path(f"{temp}-shm")):
            leftover.unlink(missing_ok=True)
    return BackupInfo(final, kind, now, final.stat().st_size)


def list_backups(directory: Path) -> list[BackupInfo]:
    """Every backup in `directory`, newest first. A missing directory is an empty list."""
    out: list[BackupInfo] = []
    if not directory.is_dir():
        return out
    for path in directory.iterdir():
        m = _ALL.match(path.name)
        if not m:
            continue
        try:  # a stray name (month 13) or a dangling symlink is skipped, never fatal
            taken = datetime.strptime(m.group(2), _STAMP).replace(tzinfo=UTC)
            out.append(BackupInfo(path, m.group(1) or "auto", taken, path.stat().st_size))
        except (ValueError, OSError):
            continue
    return sorted(out, key=lambda b: (b.taken_at, b.path.name), reverse=True)


def backup_due(
    directory: Path, now: datetime | None = None, min_age: timedelta = DUE_AFTER
) -> bool:
    """True when there is no automatic backup, or the newest is at least `min_age` old."""
    now = now or datetime.now(UTC)
    # A backup stamped in the future (clock change) must not stop backups for good:
    # only count autos stamped at or before now.
    newest = next(
        (b for b in list_backups(directory) if b.kind == "auto" and b.taken_at <= now), None
    )
    return newest is None or now - newest.taken_at >= min_age


def rotation_keep(backups: list[BackupInfo], keep_daily: int, keep_weekly: int) -> set[Path]:
    """Paths of automatic backups to keep: newest per day (N days), then per week (K weeks)."""
    autos = [b for b in backups if b.kind == "auto"]  # newest first
    keep: set[Path] = set()
    days: set = set()
    for b in autos:
        day = b.taken_at.date()
        if day not in days and len(days) < keep_daily:
            days.add(day)
            keep.add(b.path)
    weeks: set = set()
    for b in autos:
        if b.path in keep or b.taken_at.date() in days:
            continue
        week = b.taken_at.isocalendar()[:2]
        if week not in weeks and len(weeks) < keep_weekly:
            weeks.add(week)
            keep.add(b.path)
    return keep


def rotate(directory: Path, keep_daily: int = 7, keep_weekly: int = 4) -> list[Path]:
    """Delete backups outside the keep sets; returns the deleted paths.

    Automatic ones follow the daily/weekly rule; manual and pre-restore ones keep
    only their newest KEEP_MANUAL / KEEP_PRERESTORE / KEEP_PREUPDATE so the folder
    cannot grow forever.
    """
    backups = list_backups(directory)
    keep = rotation_keep(backups, keep_daily, keep_weekly)
    gone = [b.path for b in backups if b.kind == "auto" and b.path not in keep]
    kept = (("manual", KEEP_MANUAL), ("prerestore", KEEP_PRERESTORE), ("preupdate", KEEP_PREUPDATE))
    for kind, limit in kept:
        gone += [b.path for b in [x for x in backups if x.kind == kind][limit:]]
    for path in gone:
        path.unlink(missing_ok=True)
    return gone


def run_scheduled(
    settings,
    *,
    now: datetime | None = None,
    force: bool = False,
    min_age: timedelta = DUE_AFTER,
) -> BackupInfo | None:
    """Back up when due (or `force`), then rotate. Returns the new backup or None."""
    directory = settings.effective_backup_dir
    if not force and not backup_due(directory, now, min_age):
        return None
    info = create_backup(settings.database_path, directory, now=now)
    rotate(directory, settings.backup_keep_daily, settings.backup_keep_weekly)
    return info

"""SQLite health checks and the daemon's startup verdict.

Purpose    : Say, in plain words, whether the database file is sound: a fast
             `quick_check` at daemon start, and the full `integrity_check` plus
             `foreign_key_check` for `findplus db check` and `findplus doctor`.
Inputs     : A database path (opened read-only, never written) or Settings.
Outputs    : `CheckReport`; `DbHealth` (what the dashboard banner reads).
Constraints: Read-only. A damaged file is never deleted or "repaired" here: the
             daemon turns read-only (see `startup_check`) and the banner points
             the owner at `findplus db restore`. Module state is one verdict per
             process, set once at startup.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

#: Cap on the lines kept from a failing PRAGMA, so a ruined file cannot flood the log.
_MAX_PROBLEMS = 20


@dataclass(frozen=True, slots=True)
class CheckReport:
    """Result of checking one database file."""

    path: Path
    quick: list[str] = field(default_factory=list)
    integrity: list[str] = field(default_factory=list)
    foreign_keys: list[str] = field(default_factory=list)
    unreadable: str | None = None

    @property
    def ok(self) -> bool:
        return not (self.unreadable or self.quick or self.integrity or self.foreign_keys)

    @property
    def problems(self) -> list[str]:
        out = [self.unreadable] if self.unreadable else []
        return [*out, *self.quick, *self.integrity, *self.foreign_keys][:_MAX_PROBLEMS]


def _pragma_lines(conn: sqlite3.Connection, pragma: str) -> list[str]:
    """Problem lines from a check PRAGMA; an empty list means it said `ok`."""
    rows = [str(r[0]) for r in conn.execute(f"PRAGMA {pragma}").fetchall()]
    return [] if rows == ["ok"] else rows[:_MAX_PROBLEMS]


def _fk_lines(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    return [f"row {r[1]} in {r[0]} points at a missing {r[2]}" for r in rows[:_MAX_PROBLEMS]]


def open_readonly(path: Path) -> sqlite3.Connection:
    """A read-only connection (no WAL file is created for a copy opened this way)."""
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def check_database(path: Path, *, full: bool = False) -> CheckReport:
    """`quick_check` always; with `full`, also `integrity_check` and `foreign_key_check`."""
    if not path.exists():
        return CheckReport(path, unreadable="The database file does not exist.")
    try:
        conn = open_readonly(path)
    except sqlite3.Error as exc:
        return CheckReport(path, unreadable=f"The database file cannot be opened: {exc}")
    try:
        quick = _pragma_lines(conn, "quick_check")
        if not full:
            return CheckReport(path, quick=quick)
        return CheckReport(path, quick, _pragma_lines(conn, "integrity_check"), _fk_lines(conn))
    except sqlite3.DatabaseError as exc:
        return CheckReport(path, unreadable=f"The database file is damaged: {exc}")
    finally:
        conn.close()


@dataclass(frozen=True, slots=True)
class DbHealth:
    """The startup verdict the dashboard banner reads."""

    ok: bool = True
    problems: tuple[str, ...] = ()

    @property
    def read_only(self) -> bool:
        return not self.ok


_HEALTH = DbHealth()


def current_health() -> DbHealth:
    """The verdict from this process's startup check (healthy until a check says otherwise)."""
    return _HEALTH


def startup_check(database_path: Path) -> DbHealth:
    """Run `quick_check` once at daemon start and remember the verdict.

    On failure the daemon runs read-only: no polling, no pruning, no writes.
    The damaged file is left exactly as it is.
    """
    global _HEALTH
    report = check_database(database_path)
    _HEALTH = DbHealth(report.ok, tuple(report.problems))
    return _HEALTH


def reset_health() -> None:
    """Forget the verdict (tests, and after a restore in a long-lived process)."""
    global _HEALTH
    _HEALTH = DbHealth()

"""State-directory permission checks and repairs for `findplus doctor`.

Purpose    : The two permission checks (`state_dir_perms`, `sensitive_file_perms`)
             and their `--repair` counterparts, split out of `doctor.py` to keep
             that module under the 300-line file cap. `DoctorCheck` lives here
             because it is the shared result type and this is the lowest-level
             doctor module; `doctor.py` re-exports every name below, so
             `findplus.cli.doctor.check_sensitive_file_perms` still resolves.
Inputs     : the resolved state directory.
Outputs    : DoctorCheck values; the repair helpers chmod and return None.
Constraints: PRI hard rule 9 — `~/.findplus` and `~/.findplus/apple` are 0700
             and every credential/history file inside them is 0600. The check
             functions are pure; only the `repair_*` helpers mutate anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DoctorCheck:
    name: str
    label: str
    passed: bool
    detail: str
    repaired: bool = False
    repairable: bool = False


def _private_dirs(state_dir: Path) -> list[Path]:
    """Directories inside the state dir that must be 0700 in their own right.

    `apple/` holds one JSON per Apple accessory, each carrying a plist or a raw
    private key, so it is as sensitive as `logs/` (E11 review, carry-forward 26).
    """
    return [state_dir / "logs", state_dir / "apple"]


def _sensitive_files(state_dir: Path) -> list[Path]:
    """Credential stores plus the history database, its WAL siblings and the log.

    The database is the point of the app, so it belongs in this check as much
    as secrets.json does: SQLite creates `-wal`/`-shm` itself and a daemon
    started from a shell with a permissive umask leaves all three readable.
    The per-accessory Apple key files are globbed rather than named because
    there is one per device and the set changes as accessories are added.
    """
    from findplus.config import get_settings

    files = [state_dir / name for name in ("secrets.json", "alerts.json", "apple-account.json")]
    files.extend(sorted((state_dir / "apple").glob("*.json")))
    files.extend(get_settings().sensitive_paths())
    return files


def check_state_dir_perms(state_dir: Path) -> DoctorCheck:
    if not state_dir.exists():
        return DoctorCheck(
            "state_dir_perms",
            "State directory permissions",
            False,
            f"{state_dir} missing",
            repairable=False,
        )
    if os.name == "nt":
        return DoctorCheck(
            "state_dir_perms",
            "State directory permissions",
            True,
            "POSIX permission bits are not enforced on Windows",
            repairable=False,
        )
    mode = os.stat(state_dir).st_mode
    ok = (mode & 0o777) == 0o700
    return DoctorCheck(
        "state_dir_perms",
        "State directory permissions",
        ok,
        f"{state_dir} mode {oct(mode & 0o777)}",
        repairable=True,
    )


def _fail(detail: str) -> DoctorCheck:
    return DoctorCheck(
        "sensitive_file_perms", "Sensitive file permissions", False, detail, repairable=True
    )


def check_sensitive_file_perms(state_dir: Path) -> DoctorCheck:
    if os.name == "nt":
        return DoctorCheck(
            "sensitive_file_perms",
            "Sensitive file permissions",
            True,
            "POSIX permission bits are not enforced on Windows",
            repairable=False,
        )
    for p in _sensitive_files(state_dir):
        if not p.exists():
            continue
        mode = os.stat(p).st_mode & 0o777
        if mode != 0o600:
            return _fail(f"{p} mode {oct(mode)} (want 0o600)")
    for d in _private_dirs(state_dir):
        if not d.is_dir():
            continue
        mode = os.stat(d).st_mode & 0o777
        if mode != 0o700:
            return _fail(f"{d} mode {oct(mode)} (want 0o700)")
    return DoctorCheck(
        "sensitive_file_perms", "Sensitive file permissions", True, "all 0600", repairable=True
    )


def repair_state_dir_perms(state_dir: Path) -> None:
    os.chmod(state_dir, 0o700)


def repair_sensitive_file_perms(state_dir: Path) -> None:
    for p in _sensitive_files(state_dir):
        if p.exists():
            os.chmod(p, 0o600)
    for d in _private_dirs(state_dir):
        if d.is_dir():
            os.chmod(d, 0o700)

"""Get a staged update ready to install: verify it again and back up the database.

Purpose    : The last step the daemon owns before the desktop shell quits and
             update-app.sh swaps the app. It re-checks the staged build, takes a
             verified `preupdate` backup of the database, and records the attempt.
Inputs     : The state directory, the database path and the backup directory.
Outputs    : {kind, path, version, backup, result_file} for the shell, which runs
             `update-app.sh --dmg|--app <path> --result <result_file>`.
Constraints: Nothing is installed when the build changed since it was staged or
             the backup fails (UpdateError, plain words). The history database and
             everything else in the state directory stay where they are: the app
             bundle holds no data, and the new version upgrades the schema on its
             first start after its own backup (db/premigrate.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from findplus.db.backup import BackupError, create_backup
from findplus.logging_setup import get_logger
from findplus.updater import devsource, store
from findplus.updater.download import sha256_of
from findplus.updater.release import UpdateError
from findplus.updater.status import result_path, staged_update

log = get_logger(__name__)


def _verify(staged: dict[str, Any]) -> None:
    path = Path(staged["path"])
    if staged.get("kind") == "app":
        if devsource.fingerprint_app(path) != staged.get("fingerprint"):
            raise UpdateError(
                "The developer build changed after Find+ found it. "
                "The new build is picked up within a few minutes."
            )
        return
    if sha256_of(path) != staged.get("sha256"):
        raise UpdateError("The downloaded update changed on disk, so it was not installed.")


def _backup(database: Path, backup_dir: Path) -> str | None:
    if not database.exists():
        return None  # nothing recorded yet, so nothing to lose
    try:
        return str(create_backup(database, backup_dir, kind="preupdate").path)
    except BackupError as exc:
        raise UpdateError(
            f"Find+ could not back up its database first, so nothing was installed: {exc}"
        ) from exc


def prepare(
    state_dir: Path, database: Path, backup_dir: Path, *, now: datetime | None = None
) -> dict[str, Any]:
    """Verify the staged build, back up, record the attempt. Raises UpdateError."""
    state = store.load(state_dir)
    staged = staged_update(state)
    if staged is None:
        raise UpdateError("There is no update ready to install.")
    try:
        _verify(staged)
    except OSError as exc:
        raise UpdateError("The staged update cannot be read, so it was not installed.") from exc
    backup = _backup(database, backup_dir)
    stamp = (now or datetime.now(UTC)).isoformat()
    result = result_path(state_dir)
    result.unlink(missing_ok=True)
    keys = ("version", "fingerprint", "source")
    state["attempt"] = {**{k: staged.get(k) for k in keys}, "at": stamp}
    state["backup"] = {"path": backup, "at": stamp}
    store.save(state_dir, state)
    log.info("update_prepared", version=staged["version"], backup=backup)
    return {
        "kind": staged.get("kind", "dmg"),
        "path": staged["path"],
        "version": staged["version"],
        "backup": backup,
        "result_file": str(result),
    }

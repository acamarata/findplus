"""Where the update stands: the staged build, the last install attempt, the status body.

Purpose    : Decide whether a staged update is still worth installing, whether the
             last install attempt finished, tidy up after a successful one, and
             build the GET /api/update/status body.
Inputs     : The state directory; `<state>/updates/last-result`, written by
             update-app.sh (`ok <version>` or `failed <reason>`).
Outputs    : Plain dicts; `tidy()` rewrites update.json and deletes stale downloads.
Constraints: An attempt that failed, or that never reported back before this
             daemon started, blocks automatic installs of that same build, so a
             bad update cannot restart the app over and over. A newer build
             clears the block. Reading the status never touches the network.
"""

from __future__ import annotations

import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from findplus.logging_setup import get_logger
from findplus.updater import store
from findplus.updater.release import installed_version, is_newer, version_key

log = get_logger(__name__)

RESULT_NAME = "last-result"
#: When this daemon process started: an attempt older than this with no result did not finish.
PROCESS_STARTED = datetime.now(UTC)
#: Set while a check runs (check.py), so the status can say "checking".
BUSY = threading.Event()


def can_install_here() -> bool:
    """Only the macOS desktop app can replace itself (its sidecar is a frozen build)."""
    return sys.platform == "darwin" and bool(getattr(sys, "frozen", False))


def same_version(a: str | None, b: str | None) -> bool:
    return version_key(a) is not None and version_key(a) == version_key(b)


def dev_stamp(state: dict[str, Any]) -> str | None:
    """The fingerprint of the developer build that was last installed."""
    return (state.get("dev_installed") or {}).get("fingerprint")


def worth_installing(build: dict[str, Any] | None, current: str, stamp: str | None) -> bool:
    """A newer version, or (developer builds only) a rebuild of this version not yet installed."""
    if not build:
        return False
    if is_newer(build.get("version"), current):
        return True
    return (
        build.get("source") == "dev"
        and same_version(build.get("version"), current)
        and build.get("fingerprint") != stamp
    )


def staged_update(state: dict[str, Any], current: str | None = None) -> dict[str, Any] | None:
    """The staged build, when it is still on disk and still worth installing."""
    current = current or installed_version()
    staged = state.get("staged")
    if not isinstance(staged, dict) or not worth_installing(staged, current, dev_stamp(state)):
        return None
    return staged if Path(str(staged.get("path", ""))).exists() else None


def result_path(state_dir: Path) -> Path:
    return store.updates_dir(state_dir) / RESULT_NAME


def read_result(state_dir: Path) -> str | None:
    try:
        return result_path(state_dir).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _when(text: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


def attempt_failed(state: dict[str, Any], result: str | None) -> bool:
    """The last attempt reported a failure, or never reported before this daemon started."""
    attempt = state.get("attempt")
    if not isinstance(attempt, dict):
        return False
    if result:
        return result.startswith("failed")
    at = _when(attempt.get("at"))
    return at is not None and at < PROCESS_STARTED


def blocks(state: dict[str, Any], staged: dict[str, Any] | None, result: str | None) -> bool:
    """True when the staged build is the one whose install just failed."""
    attempt = state.get("attempt") or {}
    return bool(
        staged
        and attempt_failed(state, result)
        and attempt.get("fingerprint") == staged.get("fingerprint")
        and attempt.get("version") == staged.get("version")
    )


def tidy(state_dir: Path, current: str | None = None) -> None:
    """After a finished install: remember a developer build, drop old downloads. Never raises."""
    current = current or installed_version()
    try:
        state = store.load(state_dir)
        attempt = state.get("attempt") or {}
        result = read_result(state_dir)
        if attempt and result and result.startswith("ok"):
            if attempt.get("source") == "dev":
                state["dev_installed"] = {k: attempt.get(k) for k in ("fingerprint", "version")}
            state["installed"] = {"version": current, "at": datetime.now(UTC).isoformat()}
            state.pop("attempt", None)
            result_path(state_dir).unlink(missing_ok=True)
        if state.get("staged") and not staged_update(state, current):
            state.pop("staged", None)
            store.remove_staged(state_dir)
        store.save(state_dir, state)
    except OSError as exc:
        log.warning("update_tidy_failed", error=str(exc))


def status(state_dir: Path, *, auto: bool) -> dict[str, Any]:
    """The GET /api/update/status body. Reachable while locked, so it names no paths."""
    state = store.load(state_dir)
    staged = staged_update(state)
    result = read_result(state_dir)
    blocked = blocks(state, staged, result)
    install = can_install_here()
    latest, current = state.get("latest_version"), installed_version()
    return {
        "current_version": current,
        "auto": auto,
        "can_install": install,
        "checking": BUSY.is_set(),
        "checked_at": state.get("checked_at"),
        "latest_version": latest,
        "available": bool(state.get("available")) and is_newer(latest, current),
        "release_url": state.get("release_url"),
        "staged_version": staged["version"] if staged else None,
        "staged_source": staged.get("source", "release") if staged else None,
        "error": state.get("error"),
        "last_attempt_failed": blocked,
        "last_result": result if blocked else None,
        "auto_install_ready": bool(auto and install and staged and not blocked),
        "backup_at": (state.get("backup") or {}).get("at"),
        "installed": state.get("installed"),
    }

"""Find the update to install: a developer build first, else the newest GitHub release.

Purpose    : `scan_dev()` looks in the developer folder (local, no network) and
             `check()` asks GitHub once (release.py) and, when this process may
             install, downloads and verifies the release (download.py). Either
             way the winner is saved as `staged` for the desktop shell.
Inputs     : The state directory, the developer folder (or None), whether to
             download, a clock, an httpx client.
Outputs    : The saved state dict.
Constraints: Neither function raises: failures become `error` in plain words. One
             check runs at a time. A developer build wins unless the released
             version is higher (`choose`). Only the macOS desktop app downloads,
             because only it can install.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from findplus.logging_setup import get_logger
from findplus.updater import devsource, store
from findplus.updater.download import stage
from findplus.updater.release import (
    Release,
    UpdateError,
    fetch_latest,
    installed_version,
    is_newer,
)
from findplus.updater.status import BUSY, dev_stamp, tidy, worth_installing

log = get_logger(__name__)

_LOCK = threading.Lock()


def choose(dev: dict[str, Any] | None, release: str | None, current: str, stamp: str | None) -> str:
    """ "dev", "release" or "none": a developer build wins unless the release is higher."""
    dev_ok = worth_installing(dev, current, stamp)
    rel_ok = is_newer(release, current)
    if dev_ok and rel_ok:
        return "release" if is_newer(release, dev["version"]) else "dev"  # type: ignore[index]
    return "dev" if dev_ok else "release" if rel_ok else "none"


def _stage(state: dict[str, Any], build: dict[str, Any] | None, state_dir: Path) -> None:
    if build is None:
        state.pop("staged", None)
        store.remove_staged(state_dir)
        return
    if build.get("source") == "dev":
        store.remove_staged(state_dir)  # a downloaded release is not needed any more
    state["staged"] = build


def _release_build(release: Release, state_dir: Path, client) -> dict[str, Any]:
    staged = stage(release, store.updates_dir(state_dir, create=True), client)
    store.remove_staged(state_dir, keep=staged["name"])
    return {**staged, "source": "release", "kind": "dmg", "fingerprint": staged["sha256"]}


def scan_dev(state_dir: Path, dev_dir: Path | None) -> dict[str, Any]:
    """Stage the developer build when it beats what is staged now. Local only."""
    with _LOCK:
        state = store.load(state_dir)
        dev = devsource.find_build(dev_dir)
        staged = state.get("staged") or {}
        if not dev or staged.get("fingerprint") == dev["fingerprint"]:
            return state
        rival = staged.get("version") if staged.get("source") == "release" else None
        if choose(dev, rival, installed_version(), dev_stamp(state)) == "dev":
            _stage(state, dev, state_dir)
            store.save(state_dir, state)
            log.info("update_dev_build_staged", version=dev["version"])
        return state


def _check(state_dir: Path, dev_dir: Path | None, download: bool, now: datetime, client):
    state = store.load(state_dir)
    state.update(checked_at=now.isoformat(), error=None)
    dev = devsource.find_build(dev_dir)
    try:
        release = fetch_latest(client)
        version = release.version if release else None
        state.update(latest_version=version, available=is_newer(version, installed_version()))
        state["release_url"] = release.page_url if release else None
        winner = choose(dev, version, installed_version(), dev_stamp(state))
        if winner == "release" and download and release is not None:
            _stage(state, _release_build(release, state_dir, client), state_dir)
        elif winner != "release":
            _stage(state, dev if winner == "dev" else None, state_dir)
    except UpdateError as exc:
        state["error"] = str(exc)
    except Exception as exc:  # a check must never take the daemon down
        log.warning("update_check_failed", error=str(exc))
        state["error"] = "The update check failed unexpectedly."
    return state


def check(
    state_dir: Path,
    *,
    download: bool,
    dev_dir: Path | None = None,
    now: datetime | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Ask GitHub, stage the winner (downloading only when `download`), save and return."""
    with _LOCK:
        BUSY.set()
        try:
            tidy(state_dir)
            state = _check(state_dir, dev_dir, download, now or datetime.now(UTC), client)
            try:
                store.save(state_dir, state)
            except OSError as exc:
                log.warning("update_state_not_saved", error=str(exc))
            log.info("update_checked", latest=state.get("latest_version"), error=state.get("error"))
            return state
        finally:
            BUSY.clear()


def start_check(state_dir: Path, *, download: bool, dev_dir: Path | None = None) -> bool:
    """Run `check()` on a background thread. False when one is already running."""
    if BUSY.is_set():
        return False
    BUSY.set()  # before the thread starts, so the status the caller reads says "checking"
    kwargs = {"download": download, "dev_dir": dev_dir}
    thread = threading.Thread(target=check, args=(state_dir,), kwargs=kwargs, daemon=True)
    thread.name = "update-check"
    thread.start()
    return True

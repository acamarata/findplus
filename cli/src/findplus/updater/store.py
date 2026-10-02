"""The updater's small state file: what was found, what is staged, what was tried.

Purpose    : Remember the last check, the downloaded update and the last install
             attempt across daemon restarts, without touching the database.
Inputs     : The state directory (`~/.findplus` by default).
Outputs    : `<state>/updates/` (0700) holding `update.json` (0600) and the
             staged dmg.
Constraints: A missing or unreadable file reads as an empty state, never an
             error. Writes go to a temporary name first, then replace the file.
             Nothing else under the state directory is read or changed here.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

STATE_NAME = "update.json"


def updates_dir(state_dir: Path, *, create: bool = False) -> Path:
    """`<state>/updates`, made 0700 when `create` is set."""
    directory = state_dir / "updates"
    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            directory.chmod(0o700)
    return directory


def load(state_dir: Path) -> dict[str, Any]:
    """The saved state, or {} when there is none or it cannot be read."""
    try:
        data = json.loads((updates_dir(state_dir) / STATE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(state_dir: Path, data: dict[str, Any]) -> None:
    """Write the state atomically at 0600."""
    directory = updates_dir(state_dir, create=True)
    final = directory / STATE_NAME
    temp = directory / f".{STATE_NAME}.partial"
    temp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    if os.name != "nt":
        temp.chmod(0o600)
    os.replace(temp, final)


def remove_staged(state_dir: Path, keep: str | None = None) -> None:
    """Delete downloaded disk images in `updates/`, except the one named `keep`."""
    directory = updates_dir(state_dir)
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if path.name == keep or not (path.suffix == ".dmg" or path.name.endswith(".partial")):
            continue
        if path.name == f".{STATE_NAME}.partial":
            continue
        with contextlib.suppress(OSError):
            path.unlink()

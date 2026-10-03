"""Developer-only update source: a folder holding a locally built Find+.

Purpose    : When `updates.dev_dir` (or FINDPLUS_UPDATE_DEV_DIR) names a folder,
             the updater looks there first for `Find+.app` (directly, or in a
             `macos/` subfolder, the Tauri bundle layout) or for
             `FindPlus-<version>-aarch64.dmg` with its `.sha256` beside it, so a
             developer always runs their newest build. Off when unset.
Inputs     : The folder; a clock for the settle check.
Outputs    : A build dict {source, kind, path, version, fingerprint, sha256?}.
Constraints: Read only: nothing in the folder is changed. A build modified in the
             last SETTLE_SECONDS is skipped, so a half-written bundle is never
             picked up. The fingerprint changes whenever the build does (bundle
             plist, code signature seal, executables), so a rebuild of the same
             version is still seen as new. The env var wins over the setting.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from findplus.state import get_setting, set_setting
from findplus.updater.release import version_key

ENV = "FINDPLUS_UPDATE_DEV_DIR"
KEY = "updates.dev_dir"
SETTLE_SECONDS = 120.0
APP_NAME = "Find+.app"
_DMG = re.compile(r"^FindPlus-(\d+\.\d+\.\d+[0-9A-Za-z.\-]*)-aarch64\.dmg$")


def dev_dir(session: Session | None) -> Path | None:
    """The configured folder (env first, then the setting), or None."""
    raw = os.environ.get(ENV, "").strip()
    if not raw and session is not None:
        raw = (get_setting(session, KEY) or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_absolute() else None


def set_dev_dir(session: Session, value: object) -> None:
    """Store the folder (a full path) or clear it (None or ""). Raises ValueError."""
    if value is None or value == "":
        set_setting(session, KEY, None)
        return
    if not isinstance(value, str) or not Path(value).expanduser().is_absolute():
        raise ValueError("updates.dev_dir must be a full path, or null to turn it off.")
    set_setting(session, KEY, value)


def _files(app: Path) -> list[Path]:
    contents = app / "Contents"
    seal = contents / "_CodeSignature" / "CodeResources"
    out = [contents / "Info.plist", *sorted((contents / "MacOS").glob("*"))]
    if seal.is_file():
        return [*out, seal]
    # An unsigned build has no seal listing its resources; take their sizes and times.
    return out + sorted(p for p in (contents / "Resources").rglob("*") if p.is_file())


def fingerprint_app(app: Path) -> str:
    """A digest that changes whenever the bundle is rebuilt."""
    digest = hashlib.sha256()
    for path in _files(app):
        st = path.stat()
        digest.update(f"{path.relative_to(app)}|{st.st_size}|{st.st_mtime_ns}\n".encode())
        if path.name in ("Info.plist", "CodeResources"):
            digest.update(path.read_bytes())
    return digest.hexdigest()


def app_version(app: Path) -> str | None:
    try:
        with (app / "Contents" / "Info.plist").open("rb") as fh:
            value = plistlib.load(fh).get("CFBundleShortVersionString")
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    return str(value) if value else None


def _settled(paths: list[Path], now: float) -> bool:
    return all(now - p.stat().st_mtime >= SETTLE_SECONDS for p in paths)


def _app_build(directory: Path, now: float) -> dict[str, Any] | None:
    for app in (directory / APP_NAME, directory / "macos" / APP_NAME):
        version = app_version(app) if app.is_dir() else None
        if version and version_key(version) and _settled(_files(app), now):
            return {
                "source": "dev",
                "kind": "app",
                "path": str(app),
                "version": version,
                "fingerprint": fingerprint_app(app),
            }
    return None


def _dmg_build(directory: Path, now: float) -> dict[str, Any] | None:
    found = []
    for dmg in directory.glob("FindPlus-*-aarch64.dmg"):
        m = _DMG.match(dmg.name)
        sha = dmg.with_name(dmg.name + ".sha256")
        if m and version_key(m.group(1)) and sha.is_file() and _settled([dmg, sha], now):
            found.append((version_key(m.group(1)), dmg.stat().st_mtime, dmg, m.group(1), sha))
    if not found:
        return None
    _key, _mtime, dmg, version, sha = max(found, key=lambda f: (f[0], f[1]))
    want = (sha.read_text(encoding="utf-8").split() or [""])[0].lower()
    return {
        "source": "dev",
        "kind": "dmg",
        "path": str(dmg),
        "version": version,
        "fingerprint": want,
        "sha256": want,
    }


def find_build(directory: Path | None, now: float | None = None) -> dict[str, Any] | None:
    """The newest settled build in `directory`, or None. Never raises."""
    if directory is None or not directory.is_dir():
        return None
    now = time.time() if now is None else now
    try:
        builds = [b for b in (_app_build(directory, now), _dmg_build(directory, now)) if b]
    except OSError:
        return None
    return max(builds, key=lambda b: version_key(b["version"]), default=None)

"""The version of the Find+.app this frozen daemon ships inside, if any.

Purpose    : The app's Info.plist is the version the owner installed (tauri.conf.json,
             baked at build time). The frozen sidecar's own package metadata can be
             stale: 1.2.0 and 1.2.1 shipped a sidecar whose dist-info said 1.1.5, so the
             1.2.1 updater saw its own release as newer and would reinstall it. Inside an
             app bundle, the bundle's version wins.
Inputs     : sys.frozen and sys.executable (the PyInstaller sidecar lives at
             Find+.app/Contents/Resources/resources/findplus-daemon/findplus-daemon).
Outputs    : `bundle_version()` -> "1.2.2" or None (not frozen, not in an .app, unreadable).
Constraints: Standard library only; runs at package import, so it never raises.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path


def enclosing_app(executable: Path) -> Path | None:
    """The nearest parent directory named *.app, or None."""
    for parent in executable.parents:
        if parent.suffix == ".app":
            return parent
    return None


def bundle_version(executable: str | None = None, frozen: bool | None = None) -> str | None:
    """CFBundleShortVersionString of the enclosing .app for a frozen build, else None."""
    if not (getattr(sys, "frozen", False) if frozen is None else frozen):
        return None
    app = enclosing_app(Path(executable or sys.executable).resolve())
    if app is None:
        return None
    try:
        with (app / "Contents" / "Info.plist").open("rb") as fh:
            value = plistlib.load(fh).get("CFBundleShortVersionString")
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    return str(value) if value else None

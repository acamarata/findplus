"""Locate the shipped Find+ Chrome helper, copy it somewhere the user can load,
and open Chrome's extensions page.

Purpose    : The helper extension (repo `browser-helper/`) ships inside the
             wheel and the PyInstaller sidecar at `findplus/browser_helper/`.
             The dashboard's one-time install UX copies it to a stable folder
             under the state dir and reveals it, and opens chrome://extensions
             in the user's Google Chrome.
Constraints: No browser is launched here except that one explicit user action
             (open the extensions page in Google Chrome); revealing a folder is
             a file-manager action, not a browser. Tests mock subprocess.
"""

from __future__ import annotations

import importlib.resources as _ir
import json
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_DIRNAME = "browser-helper"
_PACKAGE_SUBDIR = "browser_helper"


def _candidates() -> tuple[Path, Path]:
    packaged = Path(str(_ir.files("findplus").joinpath(_PACKAGE_SUBDIR)))
    repo = Path(__file__).resolve().parents[5] / _REPO_DIRNAME
    return packaged, repo


def packaged_helper_dir() -> Path:
    """The shipped extension directory: the packaged copy if present, else the
    repo source. Returned even when absent, so callers can report a clear path."""
    packaged, repo = _candidates()
    return packaged if packaged.is_dir() else repo


def helper_available() -> tuple[bool, str]:
    """(True, "") when the extension files are on disk, else (False, reason)."""
    directory = packaged_helper_dir()
    if (directory / "manifest.json").is_file() and (directory / "background.js").is_file():
        return (True, "")
    return (False, f"Chrome helper files not found at {directory.as_posix()}")


def helper_version() -> str:
    """The version from the shipped manifest, or "0" when it cannot be read."""
    try:
        data = json.loads((packaged_helper_dir() / "manifest.json").read_text())
        return str(data.get("version") or "0")
    except (OSError, json.JSONDecodeError):
        return "0"


def install_helper(settings) -> Path:
    """Copy the extension to `~/.findplus/chrome-helper/<version>` (0700) and
    return that directory, so the user can Load unpacked from a stable place
    the app owns rather than from inside a bundle."""
    source = packaged_helper_dir()
    available, reason = helper_available()
    if not available:
        raise FileNotFoundError(reason)
    dest = Path(settings.state_dir) / "chrome-helper" / helper_version()
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    return dest


def _reveal_argv(path: str) -> list[str]:
    if sys.platform == "darwin":
        return ["open", path]
    if sys.platform == "win32":
        return ["explorer", path]
    return ["xdg-open", path]


_QUIET = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def reveal_helper(settings) -> Path:
    """Install the helper and reveal its folder in the file manager."""
    dest = install_helper(settings)
    subprocess.Popen(_reveal_argv(str(dest)), **_QUIET)
    return dest


def open_chrome_extensions() -> bool:
    """Open chrome://extensions in Google Chrome (the user's explicit request).

    Returns True once the launch was issued. Uses the same Google-Chrome finder
    the sign-in opener does, so it never drives another browser.
    """
    from .chrome_path import find_google_chrome

    url = "chrome://extensions"
    if sys.platform == "darwin":
        argv = ["open", "-a", "Google Chrome", url]
    else:
        chrome = find_google_chrome()
        if not chrome:
            return False
        argv = [chrome, url]
    try:
        if sys.platform == "darwin":
            subprocess.run(argv, check=True, timeout=20, **_QUIET)
        else:
            subprocess.Popen(argv, **_QUIET)
    except (OSError, subprocess.SubprocessError):
        return False
    return True

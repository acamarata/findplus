"""Which browser binary Google sign-in drives.

Purpose    : Hand undetected_chromedriver the real Google Chrome binary instead
             of letting it pick. Its own finder collects every `chromium`,
             `google-chrome` and `chrome` on PATH plus the macOS app paths into
             a *set* and takes the first one that exists. Set order follows
             Python's per-process string hashing, so on a machine that also has
             Homebrew's `chromium` wrapper on PATH, roughly every other sign-in
             launched that wrapper, chromedriver could not attach to it, and the
             sign-in failed with "cannot connect to chrome ... chrome not
             reachable" (found verifying 1.1.3; 1.1.2 failed the same way).
Inputs     : sys.platform, PATH, the per-platform install locations.
Outputs    : chrome_kwargs(): {"browser_executable_path": path} when Google
             Chrome is found, else {} so undetected_chromedriver keeps its own
             search (a Chromium-only machine still works as before).
Constraints: Google Chrome always wins over Chromium. No vendored code is
             touched (PRI rule 8); browser.py passes the kwargs to uc.Chrome.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_MAC_APP = "Google Chrome.app/Contents/MacOS/Google Chrome"


def _candidates() -> list[str | None]:
    """Google Chrome locations for this platform, most likely first."""
    if sys.platform == "darwin":
        return [
            str(Path("/Applications") / _MAC_APP),
            str(Path.home() / "Applications" / _MAC_APP),
        ]
    if sys.platform == "win32":
        found: list[str | None] = [shutil.which("chrome"), shutil.which("chrome.exe")]
        for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env_var)
            if base:
                found.append(str(Path(base, "Google", "Chrome", "Application", "chrome.exe")))
        return found
    return [
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        "/usr/bin/google-chrome",
        "/usr/local/bin/google-chrome",
        "/opt/google/chrome/chrome",
    ]


def find_google_chrome() -> str | None:
    """The first Google Chrome binary that exists, or None."""
    for candidate in _candidates():
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def chrome_kwargs() -> dict[str, str]:
    """Keyword arguments for uc.Chrome() that pin Google Chrome when present."""
    path = find_google_chrome()
    return {"browser_executable_path": path} if path else {}

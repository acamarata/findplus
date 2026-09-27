"""Open Google's sign-in page in the Chrome people already use.

Purpose    : First step of the main-Chrome sign-in (`POST
             /api/auth/google/open`). Opens accounts.google.com/EmbeddedSetup
             as a normal tab of the user's own Google Chrome, where they sign
             in and copy the `oauth_token` cookie (token_signin.py explains
             why that cookie). Nothing here drives or inspects the browser.
Inputs     : sys.platform and chrome_path.find_google_chrome().
Outputs    : `open_sign_in_page()` -> "chrome" or "default" (which browser got
             the page, so the dashboard can name it). Raises BrowserOpenError
             when nothing could be opened.
Constraints: argv is always a list (no shell). macOS uses `open -a "Google
             Chrome"`, which hands the URL to the running Chrome and its
             default profile instead of starting a second instance. Windows and
             Linux launch the found binary with the URL, which Chrome forwards
             to a running instance the same way. Without Google Chrome, the
             system default browser gets the page.
"""

from __future__ import annotations

import subprocess
import sys
import webbrowser

from .chrome_path import find_google_chrome

EMBEDDED_SETUP_URL = "https://accounts.google.com/EmbeddedSetup"

MSG_OPEN_FAILED = (
    "Find+ could not open a browser. Open accounts.google.com/EmbeddedSetup in Chrome "
    "yourself, then follow the steps below."
)


class BrowserOpenError(Exception):
    """No browser could be opened; `str(exc)` is written for a person."""


def chrome_argv(chrome: str, url: str) -> list[str]:
    """The command that opens `url` in the user's Google Chrome on this platform."""
    if sys.platform == "darwin":
        return ["open", "-a", "Google Chrome", url]
    return [chrome, url]


def _launch_chrome(chrome: str, url: str) -> bool:
    """True once Chrome accepted the URL. `open` returns at once; a binary is detached."""
    argv = chrome_argv(chrome, url)
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL}
    try:
        if sys.platform == "darwin":
            subprocess.run(argv, check=True, timeout=20, stderr=subprocess.DEVNULL, **quiet)
        elif sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(argv, creationflags=flags, stderr=subprocess.DEVNULL, **quiet)
        else:
            subprocess.Popen(argv, start_new_session=True, stderr=subprocess.DEVNULL, **quiet)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def open_sign_in_page(url: str = EMBEDDED_SETUP_URL) -> str:
    """Open `url` in Google Chrome, else the default browser. Returns which one."""
    chrome = find_google_chrome()
    if chrome and _launch_chrome(chrome, url):
        return "chrome"
    try:
        opened = webbrowser.open(url)
    except webbrowser.Error:
        opened = False
    if opened:
        return "default"
    raise BrowserOpenError(MSG_OPEN_FAILED)

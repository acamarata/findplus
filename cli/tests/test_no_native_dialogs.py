"""Guard: no web/app file may call the native window.confirm/prompt/alert.

Purpose    : UAT6-N21 replaced every window.confirm()/window.prompt()/
             window.alert() call under web/app with the shared
             components/confirm-dialog.js chrome (native dialogs read as
             "127.0.0.1:8747 says…", look unfinished, and window.prompt() is
             unsupported in the Tauri desktop shell's WebView). This proves
             the regression never comes back, the same "grep the whole tree"
             shape test_web_sizes.py already uses for its own caps.
Inputs     : None -- reads every web/app/**/*.js file.
Outputs    : None (asserts).
Constraints: Comments are stripped before the check (this file's own module
             docstring and confirm-dialog.js's header both mention
             "window.confirm()" by name); a real call is never inside a
             comment in this codebase's style. Not a full JS parser -- string
             literals are not stripped, but nothing under web/app puts a
             native dialog call inside a string.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB_APP_DIR = Path(__file__).resolve().parents[2] / "web" / "app"

_NATIVE_DIALOG_CALL = re.compile(r"\bwindow\.(confirm|prompt|alert)\s*\(")


def _strip_comments(text: str) -> str:
    """Blank out /* */ and // comment contents (newlines kept, so a match's
    line number in the caller's own error message still points at the real
    source line)."""
    out = []
    i, n = 0, len(text)
    while i < n:
        two = text[i : i + 2]
        if two == "/*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:j]))
            i = j
            continue
        if two == "//":
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def test_no_native_confirm_prompt_or_alert_under_web_app() -> None:
    offenders = []
    for path in sorted(WEB_APP_DIR.rglob("*.js")):
        cleaned = _strip_comments(path.read_text(encoding="utf-8"))
        for match in _NATIVE_DIALOG_CALL.finditer(cleaned):
            lineno = cleaned.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(WEB_APP_DIR)}:{lineno} window.{match.group(1)}()")
    assert not offenders, "native dialog calls (use components/confirm-dialog.js):\n" + "\n".join(
        offenders
    )

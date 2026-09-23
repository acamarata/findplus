"""The PRI rule-7 size caps (loop2 B2), applied to web/app/**/*.js and
web/**/*.css.

Sibling of test_api_sizes.py/test_src_sizes.py: the same idea, ported to JS
since there is no `ast` module for it. Python has no JS parser in this venv
(no acorn under web/app, no node_modules) so this walks a "cleaned" copy of
each file -- comments and string/template-literal contents blanked to spaces,
same length and line breaks preserved -- and finds function-shaped blocks by
regex (a `function` declaration, an arrow assigned to a `const`/`let`/`var`,
or a `name(...) {` method/handler shorthand), then measures each one by
brace-depth from its own `{` to the matching `}`. It is a heuristic, not a
real parser, but the repo's actual style (braces open on the same line,
handlers closed the same way) is exactly what it is built to read.

Both caps are enforced across every file under web/app/ -- nothing there
exceeds either one (loop2 L2-13 split the last six function-cap offenders:
icon-picker.js, devices_dialog.js, places_dialog.js, settings.js,
_group_pickers.js, signin_apple.js). There is no per-loop allowlist: any new
file or function that crosses a cap fails this test.

The file-line cap also applies to every stylesheet under web/ (components.css
and style.css both split a second time to stay under it, 2026-09-23), skipping
`vendor/` the same way test_src_sizes.py skips vendored Python -- leaflet.css
is third-party and never edited (PRI rule 8's spirit, applied to CSS).
"""

from __future__ import annotations

import re
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
WEB_APP_DIR = WEB_DIR / "app"

FUNCTION_CAP = 50
FILE_CAP = 300

_RESERVED = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "else",
    "do",
    "try",
    "finally",
    "function",
    "return",
    "class",
    "with",
    "constructor",
}

_FUNC_DECL = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z0-9_$]*)\s*\([^()]*\)\s*\{\s*$"
)
_ARROW_ASSIGN = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?"
    r"(?:\([^()]*\)|[A-Za-z0-9_$]+)\s*=>\s*\{\s*$"
)
_METHOD_SHORTHAND = re.compile(
    r"^\s*(?:static\s+)?(?:async\s+)?(?:\*\s*)?([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^()]*\)\s*\{\s*$"
)


def _blank_strings_and_comments(text: str) -> str:
    """Replace string/template/comment contents with spaces: same length and
    newline positions as the source, so line numbers and brace offsets stay
    valid, but nothing inside a string or comment can be mistaken for code."""
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
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:j]))
            i = j
            continue
        c = text[i]
        if c in "\"'`":
            quote = c
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    j += 1
                    break
                j += 1
            else:
                j = n
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:j]))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _find_functions(path: Path) -> list[tuple[str, int, int]]:
    """Returns (name, start_line, length_in_lines) for every function-shaped
    block: a `{` matched by regex, measured to its own balanced `}`."""
    raw = path.read_text(encoding="utf-8")
    clean = _blank_strings_and_comments(raw)
    lines = clean.splitlines(keepends=True)
    offsets = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)

    results = []
    seen_starts = set()
    for lineno, line in enumerate(lines, start=1):
        name = None
        for pattern in (_FUNC_DECL, _ARROW_ASSIGN, _METHOD_SHORTHAND):
            m = pattern.match(line)
            if m:
                name = m.group(1) or "<anonymous>"
                break
        if name is None or name in _RESERVED:
            continue
        brace_col = line.rfind("{")
        if brace_col == -1:
            continue
        start_offset = offsets[lineno - 1] + brace_col
        if start_offset in seen_starts:
            continue
        seen_starts.add(start_offset)
        depth = 0
        end_line = lineno
        for idx in range(start_offset, len(clean)):
            ch = clean[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_line = clean.count("\n", 0, idx) + 1
                    break
        results.append((name, lineno, end_line - lineno + 1))
    return results


def test_every_file_under_web_app_is_under_the_cap() -> None:
    offenders = []
    for path in sorted(WEB_APP_DIR.rglob("*.js")):
        count = len(path.read_text(encoding="utf-8").splitlines())
        if count > FILE_CAP:
            offenders.append(f"{path.relative_to(WEB_APP_DIR)} is {count} lines (cap {FILE_CAP})")
    assert not offenders, "over-cap files:\n" + "\n".join(offenders)


def test_every_function_under_web_app_is_under_the_cap() -> None:
    offenders = []
    for path in sorted(WEB_APP_DIR.rglob("*.js")):
        rel = path.relative_to(WEB_APP_DIR)
        for name, lineno, length in _find_functions(path):
            if length > FUNCTION_CAP:
                offenders.append(f"{rel}:{lineno} {name}() is {length} lines (cap {FUNCTION_CAP})")
    assert not offenders, "over-cap functions:\n" + "\n".join(offenders)


def test_every_stylesheet_under_web_is_under_the_cap() -> None:
    offenders = []
    for path in sorted(WEB_DIR.rglob("*.css")):
        if "vendor" in path.relative_to(WEB_DIR).parts:
            continue
        count = len(path.read_text(encoding="utf-8").splitlines())
        if count > FILE_CAP:
            offenders.append(f"{path.relative_to(WEB_DIR)} is {count} lines (cap {FILE_CAP})")
    assert not offenders, "over-cap stylesheets:\n" + "\n".join(offenders)

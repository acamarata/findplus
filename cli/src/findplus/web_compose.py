"""Compose the dashboard page from its shell and the per-tab partial files.

Purpose    : web/index.html ran past the 300-line file cap (CF-1). Its tab panels
             and the Settings dialog body now live in web/partials/*.html, and
             this module puts them back together server-side so the browser still
             receives one complete document.
Inputs     : The static directory holding index.html and partials/.
Outputs    : The composed HTML string, built once at startup.
Constraints: Composition is server-side on purpose. Fetching the partials from
             the client would populate the DOM after first paint, which breaks
             every script and test that assumes the markup is there at parse
             time. A missing or unreadable partial raises at startup rather than
             serving a page with a hole in it.
"""

from __future__ import annotations

import re
from pathlib import Path

#: `<!-- @partial: name -->`, the placeholder each shell element carries.
_MARKER = re.compile(r"[ \t]*<!--[ \t]*@partial:[ \t]*([a-z0-9_-]+)[ \t]*-->[ \t]*\n?")


class MissingPartialError(RuntimeError):
    """A marker in the shell names a partial file that is not on disk."""


def compose_index(static_dir: Path) -> str:
    """Return index.html with every `@partial` marker replaced by its file.

    Raises MissingPartialError when a marker has no matching file, so a packaging
    mistake fails at startup instead of serving a dashboard with a missing tab.
    """
    shell_path = static_dir / "index.html"
    shell = shell_path.read_text(encoding="utf-8")
    partials_dir = static_dir / "partials"

    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        path = partials_dir / f"{name}.html"
        if not path.is_file():
            missing.append(name)
            return match.group(0)
        return path.read_text(encoding="utf-8")

    composed = _MARKER.sub(_replace, shell)
    if missing:
        raise MissingPartialError(
            f"index.html references partial(s) with no file in {partials_dir}: "
            + ", ".join(sorted(missing))
        )
    return composed


def partial_names(static_dir: Path) -> list[str]:
    """Every partial name index.html asks for, in the order the markers appear."""
    shell = (static_dir / "index.html").read_text(encoding="utf-8")
    return _MARKER.findall(shell)

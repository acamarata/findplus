"""Nothing in Find+ may open a real program while tests (or fixtures) run.

Every module that can launch Finder, Chrome, a browser or the app must consult
`findplus.launch_guard.launching_disabled()`; this scans the source for the
launch calls and fails when one is unguarded.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "findplus"
LAUNCH = re.compile(
    r'webbrowser\.open|"xdg-open"|"explorer"|\["open"|"open", "-a"|"open",|osascript'
)


def _launchers() -> list[Path]:
    out = []
    for p in sorted(SRC.rglob("*.py")):
        if p.name == "launch_guard.py" or "_vendor" in p.parts:
            continue
        if LAUNCH.search(p.read_text(encoding="utf-8")):
            out.append(p)
    return out


@pytest.mark.parametrize("path", _launchers(), ids=lambda p: str(p.relative_to(SRC)))
def test_every_launcher_checks_the_guard(path: Path) -> None:
    assert "launching_disabled" in path.read_text(encoding="utf-8"), (
        f"{path.relative_to(SRC)} can open a real program but never calls launching_disabled()"
    )


def test_the_guard_is_on_under_pytest() -> None:
    from findplus.launch_guard import launching_disabled

    assert launching_disabled() is True


def test_reveal_and_open_extensions_do_nothing_under_pytest(tmp_path, monkeypatch) -> None:
    import subprocess

    from findplus.providers.google_findhub import browser_helper

    def boom(*a, **k):
        raise AssertionError("a program was launched")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    assert browser_helper.open_chrome_extensions() is True

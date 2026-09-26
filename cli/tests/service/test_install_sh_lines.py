"""install.sh stays inside its line budget.

Purpose    : The installer is read by people who pipe it from curl, so it is
             capped rather than allowed to grow. Ruling R-P2-1 pins the 1.1
             cap at 140 lines (specs/service-and-settings.md § Line budget
             and its "Amends P1 specs" section) even after `--start` landed --
             the spec's own trim table (header comment, uninstall's per-
             platform echo block, find_python's comment, one-line-per-arm
             case statements) buys the room instead of raising the ceiling.
Inputs     : The real install.sh.
Outputs    : One assertion on its line count.
Constraints: A budget the suite enforces, so the cap cannot drift unnoticed
             between a trim ticket and the next feature that edits the file.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "install.sh"

#: R-P2-1: the 1.1 ceiling (service-and-settings.md § Line budget). Raising it
#: needs a ruling, not a commit message.
MAX_LINES = 140


def test_install_sh_stays_within_its_line_budget() -> None:
    lines = len(INSTALL_SH.read_text(encoding="utf-8").splitlines())

    assert lines <= MAX_LINES, f"install.sh is {lines} lines, budget is {MAX_LINES}"

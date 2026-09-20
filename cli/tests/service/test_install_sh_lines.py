"""install.sh stays inside its line budget.

Purpose    : The installer is read by people who pipe it from curl, so it is
             capped rather than allowed to grow. Ruling R-P2-1 sets the 1.1 cap
             at 140 lines; ruling R-P2-14 sets this trim's target at 126, or
             132 if 126 is unreachable with the manual-fallback commands kept.
             Packaging round 2 (F6 PATH check, F8 venv message, F9 broken-venv
             rebuild) took it to that 132 fallback, and packaging round 3 F1
             (the GitHub-sdist fallback, without which the README's one-liner
             fails outright) takes it to 140 exactly. Every line added since
             126 fixes a path a user actually walks; none is decoration.
Inputs     : The real install.sh.
Outputs    : One assertion on its line count.
Constraints: A budget the suite enforces, so the cap cannot drift unnoticed
             between a trim ticket and the next feature that edits the file.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "install.sh"

#: R-P2-14's 132 fallback, plus packaging round 3 F1's GitHub-sdist fallback,
#: lands exactly on R-P2-1's 140 ceiling. That leaves E7-W2-S1-T2's `--start`
#: flag NO room, which is a budget question for T0, not something to resolve by
#: deleting a correctness branch. Flagged in the E1 final report.
MAX_LINES = 140


def test_install_sh_stays_within_its_line_budget() -> None:
    lines = len(INSTALL_SH.read_text().splitlines())

    assert lines <= MAX_LINES, f"install.sh is {lines} lines, budget is {MAX_LINES}"

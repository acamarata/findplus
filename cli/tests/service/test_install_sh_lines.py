"""install.sh stays inside its line budget.

Purpose    : The installer is read by people who pipe it from curl, so it is
             capped rather than allowed to grow. Ruling R-P2-1 sets the 1.1 cap
             at 140 lines; ruling R-P2-14 sets this trim's target at 126, or
             132 if 126 is unreachable with the manual-fallback commands kept.
             Packaging round 2 (F6 PATH check, F8 venv message, F9 broken-venv
             rebuild) added three user-facing correctness branches, which took
             it to R-P2-14's 132 fallback. E7-W2-S1-T2's `--start` flag has the
             remaining 8 lines under the 140 ceiling.
Inputs     : The real install.sh.
Outputs    : One assertion on its line count.
Constraints: A budget the suite enforces, so the cap cannot drift unnoticed
             between a trim ticket and the next feature that edits the file.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "install.sh"

#: R-P2-14. E7-W2-S1-T2 raises the ceiling it must stay under to 140.
MAX_LINES = 132


def test_install_sh_stays_within_its_line_budget() -> None:
    lines = len(INSTALL_SH.read_text().splitlines())

    assert lines <= MAX_LINES, f"install.sh is {lines} lines, budget is {MAX_LINES}"

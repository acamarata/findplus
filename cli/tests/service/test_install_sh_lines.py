"""install.sh stays inside its line budget.

Purpose    : The installer is read by people who pipe it from curl, so it is
             capped rather than allowed to grow. Ruling R-P2-21 sets the 1.1 cap
             at 160 lines, raised from R-P2-1's 140 once E1's three adversarial
             rounds had spent the whole 140 on user-facing correctness branches
             (the PATH notice, the python3-venv package name, the broken-venv
             rebuild, the GitHub-sdist fallback) and E7-W2-S1-T2's `--start`
             flag still needed room. Every line added since R-P2-14's 126 fixes
             a path a user actually walks; none is decoration.
Inputs     : The real install.sh.
Outputs    : One assertion on its line count.
Constraints: A budget the suite enforces, so the cap cannot drift unnoticed
             between a trim ticket and the next feature that edits the file.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "install.sh"

#: R-P2-21: the 1.1 ceiling, raised from 140 when E1 closed on 140 exactly and
#: `--start` still had to land. Adding to this number needs a ruling, not a
#: commit message.
MAX_LINES = 160


def test_install_sh_stays_within_its_line_budget() -> None:
    lines = len(INSTALL_SH.read_text().splitlines())

    assert lines <= MAX_LINES, f"install.sh is {lines} lines, budget is {MAX_LINES}"

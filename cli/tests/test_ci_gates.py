"""The CI gate lists stay in step with the modules they are supposed to guard.

E1 packaging round 2 F7: splitting dispatch.py into dispatch_send.py (CR-C F3)
moved the whole channel-send path outside the 95 percent critical-path gate,
and nothing noticed — the gate names files by path, so an extracted module
silently leaves it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRITICAL_DIRS = ("alerts",)


def _gate_include() -> str:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    match = re.search(r"coverage report --fail-under=95 --include='([^']+)'", ci)
    assert match, "the critical-path coverage gate is gone from ci.yml"
    return match.group(1)


def test_every_alerts_module_is_inside_the_critical_path_gate() -> None:
    include = _gate_include()
    for path in sorted((ROOT / "cli" / "src" / "findplus" / "alerts").glob("*.py")):
        if path.name in {"__init__.py", "store.py"}:
            continue
        assert path.name in include, (
            f"{path.name} is not in ci.yml's critical-path gate; an extracted "
            "module must be added to it or the send path goes unguarded"
        )


def test_the_handoff_doc_lists_the_same_modules() -> None:
    """HANDOFF.md prints the command a human re-runs; it must not drift from CI."""
    handoff = (ROOT / ".github" / "docs" / "HANDOFF.md").read_text()
    for name in re.findall(r"\*/findplus/alerts/([a-z_]+\.py)", _gate_include()):
        assert name in handoff, f"{name} is in ci.yml's gate but not in HANDOFF.md's copy"

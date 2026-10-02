"""No dead relative links in the wiki or README, and Home.md lists every wiki page."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "packaging" / "scripts" / "check-doc-links.py"


def test_doc_links_are_alive() -> None:
    done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout

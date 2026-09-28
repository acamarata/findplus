"""Run the Chrome helper's node unit tests as part of the Python gate.

The extension logic (browser-helper/) is plain JS with no browser: helper_core
and the content scripts are covered by node:test files next to them. This shells
out to `node --test` so a normal `pytest` run exercises them too.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_HELPER = Path(__file__).resolve().parents[2] / "browser-helper"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_browser_helper_node_tests_pass() -> None:
    result = subprocess.run(
        ["node", "--test"], cwd=_HELPER, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr

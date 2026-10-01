"""install.sh answers -h/--help with usage text and exit 0, not "unknown argument"."""

from __future__ import annotations

import subprocess
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[2] / "install.sh"


def _run(flag: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALL), flag], capture_output=True, text=True, timeout=30, check=False
    )


def test_help_flags_print_usage_and_exit_zero() -> None:
    for flag in ("--help", "-h"):
        done = _run(flag)
        assert done.returncode == 0, done.stderr
        assert "Usage: install.sh" in done.stdout
        assert "--uninstall" in done.stdout


def test_unknown_flag_still_fails() -> None:
    done = _run("--nope")
    assert done.returncode == 2
    assert "unknown argument" in done.stderr

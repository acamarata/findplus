"""install.sh's confirmation prompt survives a environment with no usable tty.

Purpose    : Guard the bug where `[ -r /dev/tty ]` passed inside a container but
             opening /dev/tty failed with ENXIO, so `set -euo pipefail` killed the
             script with "/dev/tty: No such device or address" instead of asking.
             The curl-pipe install documented in .github/wiki/Install.md feeds the
             script on stdin, which is why the /dev/tty read exists at all.
Inputs     : The real install.sh, run with stdin closed and a throwaway prefix.
Outputs    : pytest assertions on the exit code and the printed text.
Constraints: Never touches the user's venv, state directory, the network or any
             service manager: the run aborts at the prompt before installing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shell installer (install.sh)")

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "install.sh"


def _run_without_tty(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run install.sh with stdin at /dev/null, so neither stdin nor a tty answers."""
    return subprocess.run(
        ["bash", str(INSTALL_SH)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        env={
            # The real PATH, unlike the uninstall tests' minimal one: this run has to
            # get past find_python() to reach the prompt. It still installs nothing,
            # because the prompt aborts before install() runs.
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path / "home"),
            "FINDPLUS_PREFIX": str(tmp_path / "prefix"),
            "FINDPLUS_BIN": str(tmp_path / "bin"),
            "FINDPLUS_STATE_DIR": str(tmp_path / "state"),
        },
    )


def test_prompt_aborts_cleanly_when_no_tty_is_readable(tmp_path: Path) -> None:
    result = _run_without_tty(tmp_path)

    assert "No such device or address" not in result.stderr
    assert "No such device or address" not in result.stdout
    assert "Aborted." in result.stdout
    assert result.returncode == 1
    assert not (tmp_path / "prefix" / "venv").exists()

"""install.sh --uninstall unloads the service before it deletes the venv.

Purpose    : Guard the ordering bug where `--uninstall` removed the venv while
             launchd/systemd were still running the daemon out of it, leaving a
             unit that points at a deleted program and no CLI left to remove it.
Inputs     : A fake FINDPLUS_PREFIX/FINDPLUS_BIN under tmp_path, with a stub
             `findplus` that records the arguments it was called with.
Outputs    : pytest assertions on that recording and on the printed fallback.
Constraints: Runs the real install.sh in a throwaway prefix. It never touches
             the user's venv, the real state directory, the network, or any
             service manager: the stub binary is all it ever executes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

# install.sh is a POSIX shell script run via `bash`; it has no Windows
# equivalent (D13: Windows service management goes through schtasks.py, not
# a shell installer), so the whole module is not applicable there.
pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="POSIX shell service uninstall (install.sh)"
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "install.sh"


def _run(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALL_SH), "--uninstall"],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(tmp_path / "home"),
            "FINDPLUS_PREFIX": str(tmp_path / "prefix"),
            "FINDPLUS_BIN": str(tmp_path / "bin"),
            "FINDPLUS_STATE_DIR": str(tmp_path / "state"),
        },
    )


@pytest.fixture
def prefix(tmp_path: Path) -> Path:
    venv_bin = tmp_path / "prefix" / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (tmp_path / "bin").mkdir()
    (tmp_path / "home").mkdir()
    return tmp_path


def _stub(venv_bin: Path, record: Path, exit_code: int = 0) -> None:
    stub = venv_bin / "findplus"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{record}"\nexit {exit_code}\n')
    stub.chmod(0o755)


def test_uninstall_unloads_the_service_before_deleting_the_venv(prefix: Path) -> None:
    venv_bin = prefix / "prefix" / "venv" / "bin"
    record = prefix / "called.txt"
    _stub(venv_bin, record)
    (prefix / "bin" / "findplus").symlink_to(venv_bin / "findplus")

    result = _run(prefix)

    assert result.returncode == 0, result.stderr
    assert record.read_text().strip() == "uninstall --yes"
    assert not (prefix / "prefix" / "venv").exists()
    assert not (prefix / "bin" / "findplus").exists()
    assert "State directory" in result.stdout


def test_uninstall_still_removes_files_when_the_service_uninstall_fails(prefix: Path) -> None:
    venv_bin = prefix / "prefix" / "venv" / "bin"
    record = prefix / "called.txt"
    _stub(venv_bin, record, exit_code=1)

    result = _run(prefix)

    assert result.returncode == 0, result.stderr
    assert record.read_text().strip() == "uninstall --yes"
    assert not (prefix / "prefix" / "venv").exists()
    assert "reported an error" in result.stderr


def test_uninstall_prints_the_manual_fallback_when_the_binary_is_gone(prefix: Path) -> None:
    """Nothing to call, so the user is told how to remove the unit by hand."""
    shutil.rmtree(prefix / "prefix" / "venv")

    result = _run(prefix)

    assert result.returncode == 0, result.stderr
    assert "is missing" in result.stderr
    assert "launchctl bootout" in result.stderr
    assert "systemctl --user disable" in result.stderr
    assert "schtasks /delete" in result.stderr

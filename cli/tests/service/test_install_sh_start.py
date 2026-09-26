"""install.sh --start chains setup and start, and treats exit 4 as success.

Purpose    : Pin specs/service-and-settings.md § 2 — `--start` runs
             `findplus setup --yes` then `findplus start --yes`, an unsigned-in
             `start` (exit 4) still leaves the install successful, any other
             non-zero exit fails the install, and the no-`--start` final line
             points at the wizard.
Inputs     : A throwaway FINDPLUS_PREFIX/BIN under tmp_path with a prebuilt venv
             holding a stub `findplus` that records its argv and exits with a
             configured code.
Outputs    : pytest assertions on the recorded argv, exit codes and stdout.
Constraints: Never installs anything: the venv already exists so install.sh
             takes its upgrade path, and pip is a stub too. No network, no real
             state dir, no service manager.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shell installer (install.sh)")

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "install.sh"


@pytest.fixture
def prefix(tmp_path: Path) -> Path:
    venv_bin = tmp_path / "prefix" / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (tmp_path / "bin").mkdir()
    (tmp_path / "home").mkdir()
    # install.sh probes the venv's interpreter and then runs its pip; both are
    # stubs so the upgrade path is taken without touching the network.
    for name in ("python", "pip"):
        exe = venv_bin / name
        exe.write_text("#!/bin/sh\nexit 0\n")
        exe.chmod(0o755)
    # find_python() runs before install() and needs a candidate that passes both
    # its version and its venv-module probe. The machine's own python3 may be
    # neither, so the test supplies one.
    tools = tmp_path / "tools"
    tools.mkdir()
    py = tools / "python3"
    py.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo "Python 3.12.0"; fi\nexit 0\n')
    py.chmod(0o755)
    return tmp_path


def _stub(venv_bin: Path, record: Path, start_exit: int = 0) -> None:
    """A `findplus` that records each invocation and fails `start` on demand."""
    stub = venv_bin / "findplus"
    stub.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{record}"\n'
        f'if [ "$1" = "start" ]; then exit {start_exit}; fi\n'
        "exit 0\n"
    )
    stub.chmod(0o755)


def _run(prefix_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALL_SH), "--yes", *args],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": f"{prefix_dir / 'tools'}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(prefix_dir / "home"),
            "FINDPLUS_PREFIX": str(prefix_dir / "prefix"),
            "FINDPLUS_BIN": str(prefix_dir / "bin"),
            "FINDPLUS_STATE_DIR": str(prefix_dir / "state"),
            "FINDPLUS_WHEEL": "findplus-0.0.0-py3-none-any.whl",
        },
    )


def test_start_calls_setup_then_start_in_order(prefix: Path) -> None:
    record = prefix / "called.txt"
    _stub(prefix / "prefix" / "venv" / "bin", record, start_exit=0)

    result = _run(prefix, "--start")

    assert result.returncode == 0, result.stderr
    assert record.read_text().split("\n")[:2] == ["setup --yes", "start --yes"]
    assert len(record.read_text().strip().splitlines()) == 2


def test_start_exit_four_is_a_successful_install(prefix: Path) -> None:
    record = prefix / "called.txt"
    _stub(prefix / "prefix" / "venv" / "bin", record, start_exit=4)

    result = _run(prefix, "--start")

    assert result.returncode == 0, result.stderr
    assert "Installed. Sign in with: findplus auth" in result.stdout
    assert "findplus auth && findplus start" not in result.stdout


def test_start_exit_one_fails_the_install(prefix: Path) -> None:
    record = prefix / "called.txt"
    _stub(prefix / "prefix" / "venv" / "bin", record, start_exit=1)

    result = _run(prefix, "--start")

    assert result.returncode != 0
    # Both calls happened; it is `start`'s own exit code that fails the install,
    # not install.sh giving up before it got there.
    assert record.read_text().strip().splitlines() == ["setup --yes", "start --yes"]
    assert "Installed. Sign in with" not in result.stdout


def test_final_message_without_start_points_at_the_wizard(prefix: Path) -> None:
    record = prefix / "called.txt"
    _stub(prefix / "prefix" / "venv" / "bin", record)

    result = _run(prefix)

    assert result.returncode == 0, result.stderr
    assert "Installed. Run: findplus setup   (or findplus auth && findplus start)" in result.stdout
    assert not record.exists()


def test_shellcheck_is_clean() -> None:
    result = subprocess.run(
        ["shellcheck", str(INSTALL_SH)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_install_sh_is_within_the_one_point_one_budget() -> None:
    lines = len(INSTALL_SH.read_text(encoding="utf-8").splitlines())
    assert lines <= 140, f"install.sh is {lines} lines, the R-P2-1 cap is 140"

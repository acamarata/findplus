"""End-to-end packaging proof: build the wheel, install it, run the CLI.

Purpose : Prove the wheel installs and works standalone — bundled migrations,
          bundled vendor tree, and the CLI commands all resolve from
          site-packages with no dependency on the repo checkout.
Constraints: @pytest.mark.slow (builds a wheel + venv); never touches the
             real HOME or the real Google/Apple account.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

import pytest


@pytest.mark.slow
def test_wheel_installs_and_migrates(tmp_path):
    """Build wheel, install into throwaway venv, run db upgrade + doctor + version."""
    smoke_dir = Path(f"/tmp/findplus-smoke-{uuid.uuid4().hex[:8]}")
    smoke_dir.mkdir()
    fake_home = smoke_dir / "home"
    fake_home.mkdir()

    # Build wheel into smoke_dir/dist/ — parents[0]=cli/tests, parents[1]=cli (build root)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(smoke_dir / "dist"),
            str(Path(__file__).parents[1]),  # cli/ dir, where cli/pyproject.toml lives
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list((smoke_dir / "dist").glob("*.whl"))
    assert len(wheels) == 1, f"Expected 1 wheel, got {wheels}"
    wheel = wheels[0]

    # Verify wheel contents
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
    assert any("migrations/versions/0001" in n for n in names), "migrations not in wheel"
    assert any("_vendor/GoogleFindMyTools/LICENSE" in n for n in names), "vendor not in wheel"

    # Create venv
    venv = smoke_dir / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    pip = venv / "bin" / "pip"
    findplus_bin = venv / "bin" / "findplus"

    # Install wheel
    subprocess.run([str(pip), "install", "--quiet", str(wheel)], check=True)

    env = {"HOME": str(fake_home), "PATH": str(venv / "bin") + ":/usr/bin:/bin"}

    # findplus --version
    r = subprocess.run([str(findplus_bin), "--version"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"--version failed: {r.stderr}"
    assert "findplus" in r.stdout.lower() or r.stdout.strip()

    # findplus db upgrade
    r = subprocess.run(
        [str(findplus_bin), "db", "upgrade"], capture_output=True, text=True, env=env
    )
    assert r.returncode == 0, f"db upgrade failed: {r.stderr}\n{r.stdout}"
    assert (fake_home / ".findplus" / "findplus.sqlite").exists()

    # findplus doctor (E7 adds checks; here we just confirm it exits 0 with paths under fake_home)
    r = subprocess.run([str(findplus_bin), "doctor"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"doctor failed: {r.stderr}\n{r.stdout}"
    assert str(fake_home) in r.stdout

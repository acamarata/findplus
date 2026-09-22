"""End-to-end packaging proof: build the wheel, install it, run the CLI.

Purpose : Prove the wheel installs and works standalone — bundled migrations,
          bundled vendor tree, and the CLI commands all resolve from
          site-packages with no dependency on the repo checkout. Also prove
          the dashboard and vendor tree survive an sdist round trip, since
          "../web" does not exist once an sdist is unpacked.
Constraints: @pytest.mark.slow (builds a wheel + venv); never touches the
             real HOME or the real Google/Apple account; uses tmp_path (no
             manually created /tmp paths) and a sysconfig-derived scripts
             directory (no hardcoded POSIX "bin").
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

# The modules ensure_gfmt_importable() imports. token_cache.py is listed by
# name because the repo .gitignore carries `token_cache*` for the user's real
# cache file, and it has been dropped from a built artefact once already.
VENDOR_BOOTSTRAP_MODULES = (
    "Auth/__init__.py",
    "Auth/token_cache.py",
    "Auth/username_provider.py",
)

_SCRIPTS_NAME = "Scripts" if sys.platform == "win32" else "bin"
_PY_NAME = "python.exe" if sys.platform == "win32" else "python"


def _venv_scripts_dir(venv: Path) -> Path:
    """Ask the venv's own interpreter where it puts scripts (sysconfig)."""
    venv_python = venv / _SCRIPTS_NAME / _PY_NAME
    out = subprocess.run(
        [str(venv_python), "-c", "import sysconfig; print(sysconfig.get_path('scripts'))"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(out.stdout.strip())


def _build_and_verify_wheel(tmp_path: Path) -> Path:
    """Build the wheel into tmp_path/dist/, verify migrations/vendor are in
    it, and return its path -- shared setup for test_wheel_installs_and_migrates."""
    # parents[0]=cli/tests, parents[1]=cli (build root, where cli/pyproject.toml lives)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(tmp_path / "dist"),
            str(Path(__file__).parents[1]),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list((tmp_path / "dist").glob("*.whl"))
    assert len(wheels) == 1, f"Expected 1 wheel, got {wheels}"
    wheel = wheels[0]

    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
    assert any("migrations/versions/0001" in n for n in names), "migrations not in wheel"
    assert any("_vendor/GoogleFindMyTools/LICENSE" in n for n in names), "vendor not in wheel"
    for mod in VENDOR_BOOTSTRAP_MODULES:
        assert f"findplus/_vendor/GoogleFindMyTools/{mod}" in names, (
            f"{mod} missing from the wheel; ensure_gfmt_importable imports it"
        )
    return wheel


@pytest.mark.slow
def test_wheel_installs_and_migrates(tmp_path):
    """Build wheel, install into throwaway venv, run db upgrade + doctor + version."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    wheel = _build_and_verify_wheel(tmp_path)

    # Create venv
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    scripts_dir = _venv_scripts_dir(venv)
    pip = scripts_dir / ("pip.exe" if sys.platform == "win32" else "pip")
    findplus_bin = scripts_dir / ("findplus.exe" if sys.platform == "win32" else "findplus")

    # Install wheel
    subprocess.run([str(pip), "install", "--quiet", str(wheel)], check=True)

    env = {"HOME": str(fake_home), "PATH": str(scripts_dir) + os.pathsep + "/usr/bin:/bin"}

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

    # findplus doctor: a fresh, unauthenticated, service-less install legitimately
    # fails the provider/units/port checks (exit 1) — that is correct diagnostic
    # behavior (P1-E7-W3-S1-T4), not a smoke-test failure. Confirm it ran to
    # completion (didn't crash) and reported paths under fake_home.
    r = subprocess.run([str(findplus_bin), "doctor"], capture_output=True, text=True, env=env)
    assert r.returncode in (0, 1), f"doctor crashed: {r.stderr}\n{r.stdout}"
    assert str(fake_home) in r.stdout


def _build_and_extract_sdist(tmp_path: Path, repo_root: Path) -> Path:
    """Build the sdist, verify LICENSE/CHANGELOG ship and no dotfile dirs
    leak into it, extract it, and return the extracted root -- shared setup
    for test_wheel_builds_from_sdist."""
    sdist_out = tmp_path / "sdist"
    subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(sdist_out), "cli"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    tarballs = list(sdist_out.glob("*.tar.gz"))
    assert len(tarballs) == 1, f"Expected 1 sdist, got {tarballs}"

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(tarballs[0]) as tf:
        tf.extractall(extracted)
    with tarfile.open(tarballs[0]) as tf:
        sdist_names = tf.getnames()

    # The sdist is published to PyPI: it must never carry per-app AI instruction
    # directories (web/.claude, web/.opencode) that the force-included web/ tree
    # would otherwise drag in, since force-include bypasses the VCS ignore rules.
    leaked = [n for n in sdist_names if "/.claude/" in n or "/.opencode/" in n]
    assert not leaked, f"dotfile directories leaked into the sdist: {leaked}"

    # LICENSE ships via the sdist's own `include` list (cli/LICENSE lives inside
    # the sdist build root); CHANGELOG.md ships via force-include from the repo
    # root, since it is not inside cli/.
    assert any(n.endswith("/LICENSE") for n in sdist_names), "LICENSE missing from sdist"
    assert any(n.endswith("/CHANGELOG.md") for n in sdist_names), "CHANGELOG.md missing from sdist"

    sdist_dirs = [p for p in extracted.iterdir() if p.is_dir()]
    assert len(sdist_dirs) == 1, f"Expected 1 extracted sdist dir, got {sdist_dirs}"
    sdist_root = sdist_dirs[0]
    assert (sdist_root / "pyproject.toml").is_file()
    return sdist_root


def _assert_wheel_carries_dashboard_and_vendor(wheel_path: Path) -> None:
    """The page-composition, vendor-bootstrap and dotfile-leak checks for the
    wheel built from an unpacked sdist -- shared assertions for
    test_wheel_builds_from_sdist."""
    with zipfile.ZipFile(wheel_path) as zf:
        names = zf.namelist()
    assert "findplus/web/static/index.html" in names
    assert "findplus/web/static/app/main.js" in names
    # The page is composed from these at startup and a missing one is now a
    # hard failure (web_compose.MissingPartialError), so the wheel must carry
    # every partial, not just the shell (CR-C-E1 F12).
    from findplus.web_compose import partial_names

    for partial in partial_names(Path(__file__).resolve().parents[2] / "web"):
        assert f"findplus/web/static/partials/{partial}.html" in names, (
            f"partial {partial} is missing from the wheel; / would fail to start"
        )
    assert any(n.startswith("findplus/_vendor/GoogleFindMyTools/") for n in names)
    for mod in VENDOR_BOOTSTRAP_MODULES:
        assert f"findplus/_vendor/GoogleFindMyTools/{mod}" in names, (
            f"{mod} lost on the sdist round trip; ensure_gfmt_importable imports it"
        )
    dashboard = [n for n in names if n.startswith("findplus/web/static/")]
    hidden = [n for n in dashboard if any(part.startswith(".") for part in n.split("/"))]
    assert not hidden, f"dotfiles leaked into the wheel dashboard: {hidden}"
    assert any(n.endswith("dist-info/licenses/LICENSE") for n in names), (
        f"LICENSE missing from wheel dist-info: {names}"
    )


@pytest.mark.slow
def test_wheel_builds_from_sdist(tmp_path):
    """Build an sdist, unpack it, then build a wheel from the unpacked tree.

    Proves cli/hatch_build.py's sdist-case branch (Path(self.root) / "web")
    actually runs: the sdist carries the dashboard as web/ per
    [tool.hatch.build.targets.sdist.force-include], and "../web" does not
    exist once the sdist is unpacked, so this exercises a different code
    path than the repo-checkout build above.
    """
    repo_root = Path(__file__).parents[2]
    sdist_root = _build_and_extract_sdist(tmp_path, repo_root)

    wheel_out = tmp_path / "wheel"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(wheel_out)],
        cwd=sdist_root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(wheel_out.glob("*.whl"))
    assert len(wheels) == 1, f"Expected 1 wheel, got {wheels}"
    _assert_wheel_carries_dashboard_and_vendor(wheels[0])

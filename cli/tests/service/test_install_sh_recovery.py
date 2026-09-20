"""install.sh's failure and recovery paths, from packaging round 2.

F6 - a successful install left `findplus` off PATH and said nothing, then told
     the user to run it ("Installed. Run: findplus auth"). ~/.local/bin is not
     on the default macOS PATH at all, and Debian's ~/.profile adds it only if
     the directory existed at login -- which it may not have, since install.sh
     had just created it.
F8 - a user holding a working Python 3.12.3 with no python3.12-venv was told
     "Python 3.12-3.14 with the venv module required", naming the version they
     already had instead of the package they were missing.
F9 - a venv whose base interpreter had vanished made pip exit 127, and
     re-running the one-liner -- the documented remedy -- could not repair it.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = (REPO_ROOT / "install.sh").read_text()


def test_a_missing_venv_module_names_the_package_to_install() -> None:
    assert "novenv" in INSTALL_SH, "a version-pass/venv-fail candidate must be remembered"
    assert "apt install" in INSTALL_SH
    assert "-venv" in INSTALL_SH


def test_a_broken_venv_is_rebuilt_rather_than_pip_installed_into() -> None:
    assert '"$VENV/bin/python" -c pass' in INSTALL_SH, "the interpreter must be probed"
    rebuild = INSTALL_SH.index('rm -rf "$VENV"')
    upgrade = INSTALL_SH.index("pip install --upgrade")
    assert rebuild < upgrade, "the probe must run before the upgrade branch"


def test_the_installer_checks_its_symlink_is_reachable() -> None:
    tail = INSTALL_SH[INSTALL_SH.index("Installed. Run: findplus auth") :]
    assert "command -v findplus" in tail, (
        "the happy path must not end by naming a command the shell cannot find"
    )
    assert "export PATH=" in tail, "a miss must print the exact line to add"
    assert "$SYMLINK" in tail, "and the full path that works right now"

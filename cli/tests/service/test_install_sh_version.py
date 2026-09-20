"""install.sh's default pin must name a version that will actually exist.

E1 packaging round 2 F1: install.sh carried VERSION_PIN=1.0.0.dev0 while
cli/pyproject.toml said 1.0.0. Only the release ASSET copy is sed-baked by
release.yml, and bump-version.sh never touched the file, so the bytes on main —
exactly what the README's `curl .../main/install.sh | bash` pipes into bash —
pinned a version no index carries. Verified in a container: the installer
printed "Package: findplus==1.0.0.dev0".
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _project_version() -> str:
    text = (ROOT / "cli" / "pyproject.toml").read_text()
    match = re.search(r'^version = "([^"]+)"', text, re.M)
    assert match, "cli/pyproject.toml has no version"
    return match.group(1)


def _default_pin() -> str:
    text = (ROOT / "install.sh").read_text()
    match = re.search(r'^VERSION_PIN="\$\{FINDPLUS_VERSION:-([^}"]+)\}"', text, re.M)
    assert match, "install.sh's VERSION_PIN is not in the expected shape"
    return match.group(1)


def test_the_installers_default_pin_is_the_project_version() -> None:
    assert _default_pin() == _project_version(), (
        "install.sh pins a different version than cli/pyproject.toml builds; "
        "run packaging/scripts/bump-version.sh, which now rewrites both"
    )


def test_bump_version_rewrites_the_installer_pin() -> None:
    """The guard against this drifting again: the bump tool owns both files."""
    script = (ROOT / "packaging" / "scripts" / "bump-version.sh").read_text()
    assert "install.sh" in script
    assert "VERSION_PIN" in script


def test_the_default_pin_is_not_a_pre_release() -> None:
    """A dev/rc suffix on main means the documented one-liner cannot resolve."""
    pin = _default_pin()
    assert not re.search(r"(dev|a|b|rc)\d*$", pin), f"install.sh pins a pre-release: {pin}"

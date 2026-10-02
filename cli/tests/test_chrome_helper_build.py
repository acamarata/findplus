"""The Chrome Web Store build script produces a valid, keyless zip standalone."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

# On Windows `bash` is the WSL launcher (no distro here), not a shell that can run these.
_NO_BASH = sys.platform == "win32" or shutil.which("bash") is None
_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "packaging" / "scripts" / "build-chrome-helper.sh"
_EXPECTED = {
    "manifest.json",
    "background.js",
    "helper_core.js",
    "content_begin.js",
    "content_unlock_main.js",
    "content_unlock_bridge.js",
}


@pytest.mark.skipif(_NO_BASH, reason="needs a real bash (not available on Windows)")
def test_build_produces_a_keyless_store_zip() -> None:
    result = subprocess.run(["bash", str(_SCRIPT)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    zips = sorted((_ROOT / "dist").glob("findplus-chrome-helper-*.zip"))
    assert zips, "no store zip was produced"
    with zipfile.ZipFile(zips[-1]) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
    assert names == _EXPECTED, names
    assert "key" not in manifest  # the store assigns its own id
    assert manifest["manifest_version"] == 3
    assert manifest["version"]


@pytest.mark.skipif(
    _NO_BASH or shutil.which("shellcheck") is None,
    reason="needs a real bash and shellcheck",
)
def test_build_script_is_shellcheck_clean() -> None:
    result = subprocess.run(
        ["shellcheck", str(_SCRIPT)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(_NO_BASH, reason="needs a real bash (not available on Windows)")
@pytest.mark.parametrize("which", ["core", "pyproject"])
def test_build_fails_when_the_versions_differ(tmp_path, which) -> None:
    """manifest.json, helper_core.js and cli/pyproject.toml must agree."""
    (tmp_path / "packaging" / "scripts").mkdir(parents=True)
    shutil.copy(_SCRIPT, tmp_path / "packaging" / "scripts" / _SCRIPT.name)
    shutil.copytree(_ROOT / "browser-helper", tmp_path / "browser-helper")
    (tmp_path / "cli").mkdir()
    shutil.copy(_ROOT / "cli" / "pyproject.toml", tmp_path / "cli" / "pyproject.toml")
    target = (
        tmp_path / "browser-helper" / "helper_core.js"
        if which == "core"
        else tmp_path / "cli" / "pyproject.toml"
    )
    target.write_text(target.read_text().replace("1.1.5", "9.9.9", 1))
    result = subprocess.run(
        ["bash", str(tmp_path / "packaging" / "scripts" / _SCRIPT.name)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "version mismatch" in result.stderr
    assert not (tmp_path / "dist").exists()

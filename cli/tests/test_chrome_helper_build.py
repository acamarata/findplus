"""The Chrome Web Store build script produces a valid, keyless zip standalone."""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

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


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
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


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
def test_build_script_is_shellcheck_clean() -> None:
    result = subprocess.run(
        ["shellcheck", str(_SCRIPT)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr

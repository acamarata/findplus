"""The README and Install page examples name the current release, and bump-version keeps them so.

They hard-coded v1.1.5 by hand and went stale on every release. bump-version.sh now rewrites
them; this file checks both the current text and the script's behaviour on a scratch copy.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCS = ("README.md", ".github/wiki/Install.md")


def _version() -> str:
    text = (ROOT / "cli" / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.M)
    assert match
    return match.group(1)


def test_doc_examples_name_the_project_version() -> None:
    ver = _version()
    for doc in DOCS:
        text = (ROOT / doc).read_text(encoding="utf-8")
        assert f"(for example, v{ver})" in text, doc
        assert f"releases/download/v{ver}/findplus-{ver}-py3-none-any.whl" in text, doc
        assert not re.search(r"v(?!%s\b)\d+\.\d+\.\d+/findplus-" % re.escape(ver), text), doc


def test_bump_version_rewrites_the_doc_examples(tmp_path: Path) -> None:
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    for rel in (
        "cli/pyproject.toml",
        "install.sh",
        "CHANGELOG.md",
        "browser-helper/manifest.json",
        "browser-helper/helper_core.js",
        *DOCS,
        "packaging/scripts/bump-version.sh",
    ):
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, dest)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-qm", "x"], cwd=tmp_path, check=True)
    env = {**os.environ, "FINDPLUS_YES": "1"}
    subprocess.run(
        ["bash", "packaging/scripts/bump-version.sh", "9.8.7"], cwd=tmp_path, env=env, check=True
    )
    for doc in DOCS:
        text = (tmp_path / doc).read_text(encoding="utf-8")
        assert "(for example, v9.8.7)" in text, doc
        assert "releases/download/v9.8.7/findplus-9.8.7-py3-none-any.whl" in text, doc

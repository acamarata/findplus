"""gen-api-docs.py / gen-cli-docs.py run cleanly and produce the wiki pages.

Both live outside the `findplus` package (packaging/scripts/) with hyphenated
filenames, so they are loaded via importlib rather than a normal import.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "packaging" / "scripts"


def _load(module_name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_into(module: ModuleType, tmp_path: Path, monkeypatch) -> str:
    """Run a generator with its OUTPUT redirected into `tmp_path`.

    The scripts write to the tracked `.github/wiki/*.md` files by design; a test
    run must not. Redirecting OUTPUT keeps `pytest` from silently regenerating —
    and therefore hiding — the very drift the docs-drift gate exists to catch.
    """
    out = tmp_path / module.OUTPUT.name
    monkeypatch.setattr(module, "OUTPUT", out)
    module.main()
    return out.read_text(encoding="utf-8")


def test_gen_api_docs_runs(tmp_db, tmp_path, monkeypatch) -> None:
    module = _load("gen_api_docs", "gen-api-docs.py")
    text = _run_into(module, tmp_path, monkeypatch)
    assert "## core" in text
    assert "## devices" in text
    assert "### GET /api/version" in text
    assert "### GET /api/widget" in text


def test_gen_cli_docs_runs(tmp_db, tmp_path, monkeypatch) -> None:
    module = _load("gen_cli_docs", "gen-cli-docs.py")
    text = _run_into(module, tmp_path, monkeypatch)
    assert "## findplus export" in text
    assert "## findplus serve" in text
    assert "## findplus version" in text
    assert "--group" in text


def test_generators_do_not_touch_the_repo(tmp_db, tmp_path, monkeypatch) -> None:
    """Regression guard for the redirect above: neither wiki file is rewritten."""
    stamps = {}
    for name in ("API-reference.md", "CLI-reference.md"):
        path = REPO_ROOT / ".github" / "wiki" / name
        stamps[name] = path.stat().st_mtime_ns if path.exists() else None
    for module_name, filename in (
        ("gen_api_docs2", "gen-api-docs.py"),
        ("gen_cli_docs2", "gen-cli-docs.py"),
    ):
        _run_into(_load(module_name, filename), tmp_path, monkeypatch)
    for name, before in stamps.items():
        path = REPO_ROOT / ".github" / "wiki" / name
        after = path.stat().st_mtime_ns if path.exists() else None
        assert after == before, name

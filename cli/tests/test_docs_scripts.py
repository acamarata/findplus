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


def test_gen_api_docs_runs(tmp_db) -> None:
    module = _load("gen_api_docs", "gen-api-docs.py")
    module.main()
    text = module.OUTPUT.read_text(encoding="utf-8")
    assert "## core" in text
    assert "## devices" in text


def test_gen_cli_docs_runs(tmp_db) -> None:
    module = _load("gen_cli_docs", "gen-cli-docs.py")
    module.main()
    text = module.OUTPUT.read_text(encoding="utf-8")
    assert "## findplus export" in text
    assert "## findplus serve" in text

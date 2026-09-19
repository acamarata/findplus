"""Packaging bootstrap: GoogleFindMyTools resolves and lands on sys.path."""

from __future__ import annotations

import subprocess
import sys

from findplus.providers.findhub.bootstrap import ensure_gfmt_importable


def test_editable_mode_resolves_repo_path() -> None:
    resolved = ensure_gfmt_importable()
    assert resolved.name == "GoogleFindMyTools"
    assert resolved.is_dir()
    assert str(resolved) in sys.path


def test_idempotent() -> None:
    ensure_gfmt_importable()
    count = sys.path.count(str(ensure_gfmt_importable()))
    assert count == 1


def test_core_entry_modules_do_not_import_the_deprecated_findhub_shim() -> None:
    """`findplus.findhub` warns on import (see its docstring); the real modules
    must go through `findplus.providers.google_findhub` instead. `-W error`
    turns that warning into an ImportError if any of the three still resolve
    through the shim, which a plain `import findplus.api` would not catch
    (pytest already imported the package under test by then)."""
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "error::DeprecationWarning",
            "-c",
            "import findplus.api, findplus.poller, findplus.cli.main",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

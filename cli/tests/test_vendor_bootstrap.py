"""Packaging bootstrap: GoogleFindMyTools resolves and lands on sys.path."""

from __future__ import annotations

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

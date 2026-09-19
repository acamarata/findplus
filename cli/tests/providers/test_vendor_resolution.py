"""Vendor path resolution: packaging-aware, prefers the wheel copy over the repo tree.

Regression coverage for the config.VENDOR_GFMT fix (E3 coordinator follow-up):
before this, VENDOR_GFMT was a fixed PROJECT_ROOT-relative constant that pointed
at a path which does not exist inside an installed wheel. It now resolves through
the same lookup ensure_gfmt_importable() uses, so `findplus doctor`'s "vendored"
check and config.VENDOR_GFMT stay correct in both dev-checkout and installed modes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from findplus.providers.findhub import bootstrap as pkg_bootstrap


def test_resolve_vendor_path_prefers_packaged_when_repo_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Packaged findplus/_vendor exists but PROJECT_ROOT/vendor does not."""
    packaged = tmp_path / "packaged" / "GoogleFindMyTools"
    packaged.mkdir(parents=True)
    absent_repo = tmp_path / "repo-does-not-exist" / "GoogleFindMyTools"

    monkeypatch.setattr(pkg_bootstrap, "_candidates", lambda: (packaged, absent_repo))

    assert pkg_bootstrap.resolve_vendor_path() == packaged


def test_resolve_vendor_path_falls_back_to_repo_when_packaged_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The opposite case: dev checkout, nothing packaged yet."""
    absent_packaged = tmp_path / "packaged-does-not-exist" / "GoogleFindMyTools"
    repo = tmp_path / "repo" / "GoogleFindMyTools"
    repo.mkdir(parents=True)

    monkeypatch.setattr(pkg_bootstrap, "_candidates", lambda: (absent_packaged, repo))

    assert pkg_bootstrap.resolve_vendor_path() == repo


def test_resolve_vendor_path_never_raises_when_neither_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """config.py imports VENDOR_GFMT at module load; resolution must not crash."""
    neither_a = tmp_path / "a" / "GoogleFindMyTools"
    neither_b = tmp_path / "b" / "GoogleFindMyTools"

    monkeypatch.setattr(pkg_bootstrap, "_candidates", lambda: (neither_a, neither_b))

    assert pkg_bootstrap.resolve_vendor_path() == neither_b

"""Fixtures for the updater tests: a fake GitHub, a pinned version, a state dir."""

from __future__ import annotations

from pathlib import Path

import pytest

from ._fake_github import FakeGitHub


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch):
    fake = FakeGitHub()
    monkeypatch.setenv("FINDPLUS_UPDATE_API", fake.base)
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch):
    """Pretend this Find+ is version `v` (default 1.2.1)."""
    import findplus

    def _set(v: str = "1.2.1") -> str:
        monkeypatch.setattr(findplus, "__version__", v)
        return v

    _set()
    return _set


@pytest.fixture
def state_dir(tmp_db, tmp_path: Path) -> Path:
    from findplus.config import get_settings

    path = get_settings().state_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def in_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behave like the frozen sidecar inside Find+.app on macOS."""
    from findplus.api import routes_update
    from findplus.updater import scheduler, status

    for module in (status, scheduler, routes_update):
        monkeypatch.setattr(module, "can_install_here", lambda: True)

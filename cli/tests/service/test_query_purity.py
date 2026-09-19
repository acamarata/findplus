"""Read-only queries must not create or rewire anything (build-notes 17 and 20).

Purpose : `service.plan()`, `service.watchdog_plan()`, `service.is_installed()`
          and `GoogleFindHubProvider.is_available()` are all reached from status
          surfaces (`findplus status`, `findplus providers`, `GET /api/providers`,
          the poll-loop guard). Each used to create `~/.findplus` — and, for the
          provider, monkeypatch the vendored credential store — as a side effect
          of being asked a question.
Constraints: no network, no real state dir; every path is under tmp_path.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest


def _settings(tmp_path: Path):
    from findplus.config import get_settings

    return get_settings(state_dir=tmp_path / "never-created")


def _patch_manager(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    for target in (
        "findplus.service.detect_manager",
        "findplus.service.runtime.detect_manager",
        "findplus.service.watchdog.detect_manager",
    ):
        monkeypatch.setattr(target, lambda _n=name: _n)


def test_plan_does_not_create_the_state_dir(tmp_path, monkeypatch) -> None:
    from findplus import service

    _patch_manager(monkeypatch, "launchd")
    s = _settings(tmp_path)
    service.plan(s)
    assert not s.state_dir.exists()


def test_watchdog_plan_does_not_create_the_state_dir(tmp_path, monkeypatch) -> None:
    from findplus import service

    _patch_manager(monkeypatch, "launchd")
    s = _settings(tmp_path)
    service.watchdog_plan(s)
    assert not s.state_dir.exists()


def test_is_installed_does_not_create_the_state_dir(tmp_path, monkeypatch) -> None:
    from findplus import service

    _patch_manager(monkeypatch, "launchd")
    s = _settings(tmp_path)
    assert service.is_installed(s) is False
    assert not s.state_dir.exists()


def test_install_still_creates_the_state_dir(tmp_path, monkeypatch) -> None:
    """The side effect moved into install(), it did not disappear: the unit text
    points the job's stdout/stderr at <state_dir>/logs."""
    from findplus import service

    _patch_manager(monkeypatch, "launchd")
    monkeypatch.setattr("findplus.service._proc.shutil.which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr("findplus.service._proc.subprocess.run", lambda *a, **k: None)
    s = _settings(tmp_path)
    monkeypatch.setattr(
        "findplus.service.launchd.plan_launchd",
        lambda settings, program=None: _FakePlan(tmp_path / "unit.plist"),
    )
    service.install(s, confirmed=True)
    assert s.state_dir.is_dir()
    assert s.log_dir.is_dir()


class _FakePlan:
    manager = "launchd (user)"
    platform = "test"
    unit_text = "<plist/>"
    load_command: ClassVar[list[str]] = []
    unload_command: ClassVar[list[str]] = []

    def __init__(self, unit_path: Path) -> None:
        self.unit_path = unit_path


def test_provider_is_available_has_no_side_effects(tmp_path, monkeypatch) -> None:
    """is_available() must not create the state dir or rebind the GFMT secret
    store — that is ensure_gfmt_importable()'s job, on the paths that use it."""
    from findplus.providers.google_findhub.provider import GoogleFindHubProvider

    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path / "never-created"))

    def _boom() -> None:
        raise AssertionError("is_available() called ensure_gfmt_importable()")

    monkeypatch.setattr("findplus.providers.google_findhub.bootstrap.ensure_gfmt_importable", _boom)
    available, reason = GoogleFindHubProvider().is_available()
    assert isinstance(available, bool)
    assert isinstance(reason, str)
    assert not (tmp_path / "never-created").exists()


def test_vendor_available_reports_a_reason_when_absent(monkeypatch) -> None:
    from findplus.providers.findhub import bootstrap

    missing = (Path("/nope/pkg"), Path("/nope/repo"))
    monkeypatch.setattr(bootstrap, "_candidates", lambda: missing)
    ok, reason = bootstrap.vendor_available()
    assert ok is False
    assert "/nope/pkg" in reason and "/nope/repo" in reason

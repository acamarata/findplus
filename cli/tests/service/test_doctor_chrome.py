"""`check_chrome` (UAT2 N1): every Chrome/Chromium detection path in isolation.

Purpose    : 143fb48 widened check_chrome() to mirror the vendored
             GoogleFindMyTools find_chrome() search (PATH lookups for
             google-chrome/-stable/chromium/chromium-browser, plus per-OS
             fallback paths: user-level macOS installs, Linux Chromium
             binaries). Split out of test_doctor.py to keep that file under
             the line cap (PRI rule 7); test_doctor.py keeps the one smoke
             test that just asserts the function runs without raising.
Constraints: shutil.which and Path.exists/Path.home are fully stubbed for
             every test, so these never depend on -- or are masked by -- a
             real Chrome install on the machine running the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from findplus.cli.doctor import check_chrome


def _stub_environment(
    monkeypatch: pytest.MonkeyPatch,
    which_found: frozenset[str] = frozenset(),
    extra_exists: frozenset[str] = frozenset(),
) -> None:
    """Isolate check_chrome() from the real PATH and filesystem.

    `which_found` names the commands `shutil.which` should "find" (each gets
    a fake resolved path that Path.exists then also reports as present, the
    same way a real `which` never returns a path that doesn't exist).
    `extra_exists` adds bare paths (the static macOS/Linux candidates) that
    Path.exists should report as present.
    """
    resolved = {name: f"/usr/bin/{name}" for name in which_found}
    monkeypatch.setattr("shutil.which", lambda name: resolved.get(name))
    exists_paths = set(resolved.values()) | set(extra_exists)
    monkeypatch.setattr(Path, "exists", lambda self: str(self) in exists_paths)


def test_chrome_not_found_when_nothing_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_environment(monkeypatch)
    c = check_chrome()
    assert c.passed is False
    assert c.detail == "not found"


@pytest.mark.parametrize(
    "which_name", ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
)
def test_chrome_found_via_path_lookup(monkeypatch: pytest.MonkeyPatch, which_name: str) -> None:
    _stub_environment(monkeypatch, which_found=frozenset({which_name}))
    c = check_chrome()
    assert c.passed is True
    assert c.detail == "found"


def test_chrome_found_via_darwin_system_applications(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    _stub_environment(monkeypatch, extra_exists=frozenset({"/Applications/Google Chrome.app"}))
    assert check_chrome().passed is True


def test_chrome_found_via_darwin_user_applications(monkeypatch: pytest.MonkeyPatch) -> None:
    """UAT2 N1: a per-user macOS install (~/Applications), not just system-wide."""
    fake_home = Path("/Users/fixture-user")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    user_app = str(fake_home / "Applications" / "Google Chrome.app")
    _stub_environment(monkeypatch, extra_exists=frozenset({user_app}))
    assert check_chrome().passed is True


def test_chrome_not_found_on_darwin_when_neither_applications_path_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: Path("/Users/fixture-user"))
    _stub_environment(monkeypatch)
    assert check_chrome().passed is False


@pytest.mark.parametrize(
    "linux_path",
    [
        "/usr/bin/google-chrome",
        "/usr/local/bin/google-chrome",
        "/opt/google/chrome/chrome",
        "/snap/bin/chromium",
    ],
)
def test_chrome_found_via_linux_fallback_path(
    monkeypatch: pytest.MonkeyPatch, linux_path: str
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    _stub_environment(monkeypatch, extra_exists=frozenset({linux_path}))
    assert check_chrome().passed is True


def test_chrome_not_found_on_linux_when_no_fallback_path_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    _stub_environment(monkeypatch)
    assert check_chrome().passed is False

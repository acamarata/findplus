"""`findplus selfcheck`: the frozen-build guard behind sidecar-smoke.sh.

v1.1.1's dmg crashed when Google sign-in started its Chrome helper (no
multiprocessing.freeze_support in the frozen entry point) and shipped without
the Apple Find My library. selfcheck proves both inside whatever install runs it.
"""

from __future__ import annotations

from click.testing import CliRunner

from findplus.cli import cmd_selfcheck
from findplus.cli.main import main


def test_a_spawned_child_starts_and_reports_back() -> None:
    assert cmd_selfcheck.spawn_works(timeout=60) is True


def test_selfcheck_passes_and_names_both_checks(monkeypatch) -> None:
    monkeypatch.setattr(cmd_selfcheck, "spawn_works", lambda: True)
    monkeypatch.setattr(cmd_selfcheck, "apple_import_error", lambda: None)
    result = CliRunner().invoke(main, ["selfcheck"])
    assert result.exit_code == 0, result.output
    assert "PASS  helper process (Google sign-in)" in result.output
    assert "PASS  Apple Find My library" in result.output


def test_a_missing_apple_library_fails_unless_skipped(monkeypatch) -> None:
    monkeypatch.setattr(cmd_selfcheck, "spawn_works", lambda: True)
    monkeypatch.setattr(
        cmd_selfcheck, "apple_import_error", lambda: "ModuleNotFoundError: No module named 'srp'"
    )
    failed = CliRunner().invoke(main, ["selfcheck"])
    assert failed.exit_code == 1
    assert "FAIL  Apple Find My library" in failed.output
    assert "No module named 'srp'" in failed.output
    skipped = CliRunner().invoke(main, ["selfcheck", "--no-apple"])
    assert skipped.exit_code == 0, skipped.output


def test_a_broken_helper_spawn_fails(monkeypatch) -> None:
    monkeypatch.setattr(cmd_selfcheck, "spawn_works", lambda: False)
    result = CliRunner().invoke(main, ["selfcheck", "--no-apple"])
    assert result.exit_code == 1
    assert "FAIL  helper process (Google sign-in)" in result.output


def test_every_vendored_module_find_plus_uses_imports() -> None:
    assert cmd_selfcheck.vendor_import_failures() == []


def test_a_vendor_import_failure_is_named(monkeypatch) -> None:
    monkeypatch.setattr(cmd_selfcheck, "spawn_works", lambda: True)
    monkeypatch.setattr(
        cmd_selfcheck,
        "vendor_import_failures",
        lambda: ["selenium.webdriver.support.ui: No module named 'selenium.webdriver.support.ui'"],
    )
    result = CliRunner().invoke(main, ["selfcheck", "--no-apple"])
    assert result.exit_code == 1
    assert "FAIL  Google Find Hub modules" in result.output
    assert "selenium.webdriver.support.ui" in result.output

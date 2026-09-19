"""Start-at-login: the desktop app's LaunchAgent uses the same Python
service code as the CLI (P1-E13-W6-S1-T5).

Purpose    : Prove the generated plist embeds the app's own binary path
             when --program overrides it, that the watchdog job's
             ProgramArguments carries the same program plus "watchdog",
             and that uninstall removes the plist and unloads the job.
Constraints: Path.home() is monkeypatched to a tmp_path so no test ever
             writes into the real ~/Library/LaunchAgents.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from findplus import service
from findplus.cli.main import main
from findplus.config import get_settings
from findplus.service.launchd import plan_launchd, watchdog_plan_launchd

APP_PROGRAM = "/Applications/Find+.app/Contents/MacOS/findplus-daemon"


def _patch_manager(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Same three-target patch test_service_cmds.py uses: runtime.py and
    watchdog.py import detect_manager by reference at call time."""
    monkeypatch.setattr("findplus.service.detect_manager", lambda: name)
    monkeypatch.setattr("findplus.service.runtime.detect_manager", lambda: name)
    monkeypatch.setattr("findplus.service.watchdog.detect_manager", lambda: name)


# ------------------------------------------------------------------------- a
def test_install_service_program_in_launch_agent(tmp_db) -> None:
    settings = get_settings()
    plan = plan_launchd(settings, program=APP_PROGRAM)
    import plistlib

    payload = plistlib.loads(plan.unit_text.encode())
    assert payload["ProgramArguments"][0] == APP_PROGRAM
    assert payload["ProgramArguments"][1:] == ["serve", "--foreground"]


# ------------------------------------------------------------------------- b
def test_watchdog_plan_carries_the_same_program(tmp_db) -> None:
    settings = get_settings()
    plan = watchdog_plan_launchd(settings, program=APP_PROGRAM)
    import plistlib

    payload = plistlib.loads(plan.unit_text.encode())
    assert payload["ProgramArguments"] == [APP_PROGRAM, "watchdog"]


# ------------------------------------------------------------------------- c
def test_install_service_cli_help_shows_program_flag() -> None:
    result = CliRunner().invoke(main, ["install-service", "--help"])
    assert result.exit_code == 0, result.output
    assert "--program" in result.output


# ------------------------------------------------------------------------- d
def test_uninstall_removes_plist_and_unloads(
    tmp_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_manager(monkeypatch, "launchd")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    settings = get_settings()

    plan = plan_launchd(settings, program=APP_PROGRAM)
    plan.unit_path.parent.mkdir(parents=True, exist_ok=True)
    plan.unit_path.write_text(plan.unit_text, encoding="utf-8")
    assert plan.unit_path.exists()

    unload_calls: list[list[str]] = []
    monkeypatch.setattr(
        "findplus.service.runtime.subprocess.run",
        lambda cmd, **k: unload_calls.append(cmd),
    )

    service.uninstall(settings)

    assert not plan.unit_path.exists()
    assert unload_calls, "uninstall must invoke the unload command"

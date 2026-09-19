"""`--program PATH` override on `start` for the desktop-app sidecar
(P1-E7-W3-S1-T7).

Purpose : The resolved program path reaching service.install(), and that the
          plan builders embed it verbatim in the generated unit text.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from findplus.cli.main import main
from findplus.config import get_settings
from findplus.service import schtasks
from findplus.service.launchd import plan_launchd


def _native_absolute_path(posix_like: str) -> str:
    """An OS-appropriate absolute path with the same shape as `posix_like`.

    `start`'s `--program` handler does `str(Path(program_override).resolve())`
    (cmd_service.py) to turn a relative override into an absolute one. A
    driveless path like "/custom/path/x" IS already absolute on POSIX, so
    .resolve() is a no-op there — but Windows has no driveless-absolute
    concept, so the same string resolves against whatever drive the test
    happens to run from (e.g. "D:\\custom\\path\\x" on a GitHub-hosted
    runner). Give Windows a real drive-letter path instead, so the fixture
    input is meaningful on every OS the CI matrix runs.
    """
    if os.name == "nt":
        return "C:\\" + posix_like.lstrip("/").replace("/", "\\")
    return posix_like


def _track_one_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.providers.google_findhub.bootstrap.describe_stored_auth",
        lambda: {"exists": True},
    )
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device
    from findplus.state import track_devices

    with session_scope() as s:
        upsert_device(s, "TAG-1", "Keys")
        track_devices(s, ["TAG-1"], exclusive=True)


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("webbrowser.open", lambda url: None)


# ------------------------------------------------------------------------- a
def test_start_custom_program_reaches_install(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _track_one_device(monkeypatch)
    monkeypatch.setattr("findplus.service.is_installed", lambda: False)
    calls: list[dict] = []
    monkeypatch.setattr("findplus.service.install", lambda *a, **k: calls.append(k))
    monkeypatch.setattr("findplus.service.install_watchdog", lambda *a, **k: None)

    program = _native_absolute_path("/custom/path/findplus-daemon")
    result = CliRunner().invoke(main, ["start", "--yes", "--program", program])
    assert result.exit_code == 0, result.output
    assert calls[0]["program"] == str(Path(program).resolve())


# ------------------------------------------------------------------------- b
def test_start_default_program_contains_findplus(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _track_one_device(monkeypatch)
    monkeypatch.setattr("findplus.service.is_installed", lambda: False)
    calls: list[dict] = []
    monkeypatch.setattr("findplus.service.install", lambda *a, **k: calls.append(k))
    monkeypatch.setattr("findplus.service.install_watchdog", lambda *a, **k: None)

    result = CliRunner().invoke(main, ["start", "--yes"])
    assert result.exit_code == 0, result.output
    assert "findplus" in calls[0]["program"]


# ------------------------------------------------------------------------- c
def test_start_desktop_app_program_path(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _track_one_device(monkeypatch)
    monkeypatch.setattr("findplus.service.is_installed", lambda: False)
    calls: list[dict] = []
    monkeypatch.setattr("findplus.service.install", lambda *a, **k: calls.append(k))
    monkeypatch.setattr("findplus.service.install_watchdog", lambda *a, **k: None)

    program = _native_absolute_path("/Applications/Find+.app/Contents/MacOS/findplus-daemon")
    result = CliRunner().invoke(main, ["start", "--yes", "--program", program])
    assert result.exit_code == 0, result.output
    assert calls[0]["program"] == str(Path(program).resolve())


# ------------------------------------------------------------------------- d
def test_plan_launchd_program_in_program_arguments(tmp_db) -> None:
    settings = get_settings()
    plan = plan_launchd(settings, program="/custom/path/findplus-daemon")
    import plistlib

    payload = plistlib.loads(plan.unit_text.encode())
    assert "/custom/path/findplus-daemon" in payload["ProgramArguments"]


# ------------------------------------------------------------------------- e
def test_plan_schtasks_program_in_command(tmp_db) -> None:
    settings = get_settings()
    plan = schtasks.plan_schtasks(settings, program="/custom/path/findplus-daemon")
    assert "<Command>/custom/path/findplus-daemon</Command>" in plan.unit_text


# ------------------------------------------------------------------------- f
def test_start_help_mentions_program_option() -> None:
    result = CliRunner().invoke(main, ["start", "--help"])
    assert result.exit_code == 0, result.output
    assert "--program" in result.output
    assert "PATH" in result.output
    assert "daemon executable" in result.output


def test_install_service_alias_also_has_program_option() -> None:
    result = CliRunner().invoke(main, ["install-service", "--help"])
    assert result.exit_code == 0, result.output
    assert "--program" in result.output

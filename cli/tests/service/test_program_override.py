"""`--program PATH` override on `start` for the desktop-app sidecar
(P1-E7-W3-S1-T7).

Purpose : The resolved program path reaching service.install(), and that the
          plan builders embed it verbatim in the generated unit text.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from findplus.cli.main import main
from findplus.config import get_settings
from findplus.service import schtasks
from findplus.service.launchd import plan_launchd


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

    result = CliRunner().invoke(
        main, ["start", "--yes", "--program", "/custom/path/findplus-daemon"]
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["program"] == "/custom/path/findplus-daemon"


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

    program = "/Applications/Find+.app/Contents/MacOS/findplus-daemon"
    result = CliRunner().invoke(main, ["start", "--yes", "--program", program])
    assert result.exit_code == 0, result.output
    assert calls[0]["program"] == program


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

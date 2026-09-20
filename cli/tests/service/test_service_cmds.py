"""D15 start/stop/restart/status/uninstall commands (P1-E7-W3-S1-T1).

Purpose : Exercise the D15 state machine (auth -> tracked -> install/start) and
          the thin stop/restart/status/uninstall commands. Facade dispatch and
          the plan snapshots live in test_service_plans.py, `auth` in
          test_auth_cmd.py — this file was 378 lines with all three.
Constraints: Tests never touch the real ~/.findplus or the network;
             webbrowser.open is always monkeypatched.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from findplus.cli.main import main
from findplus.config import get_settings
from tests.service._helpers import patch_manager as _patch_manager


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    return opened


# --------------------------------------------------------------- a/b: no auth
def test_start_not_authenticated_prints_next_steps(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.providers.google_findhub.bootstrap.describe_stored_auth",
        lambda: {"exists": False},
    )
    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.install", lambda *a, **k: calls.append(True))

    result = CliRunner().invoke(main, ["start"])
    assert result.exit_code == 4, result.output
    assert "Find+ is not signed in yet" in result.output
    assert "findplus auth" in result.output
    assert "findplus setup" in result.output
    assert "findplus start" in result.output
    assert calls == []


# ------------------------------------------------------- c/d/e: nothing tracked
class _FakeDevice:
    def __init__(self, device_id: str, name: str) -> None:
        self.device_id = device_id
        self.name = name


def test_start_nothing_tracked_discovers_prints_and_tracks_all(
    tmp_db, monkeypatch: pytest.MonkeyPatch, _no_browser: list[str]
) -> None:
    monkeypatch.setattr(
        "findplus.providers.google_findhub.bootstrap.describe_stored_auth", lambda: {"exists": True}
    )
    monkeypatch.setattr(
        "findplus.providers.google_findhub.client.FindHubClient.list_devices",
        lambda self: [_FakeDevice("TAG-1", "Keys")],
    )
    monkeypatch.setattr("findplus.service.is_installed", lambda: False)
    install_calls: list[bool] = []
    monkeypatch.setattr("findplus.service.install", lambda *a, **k: install_calls.append(True))
    monkeypatch.setattr("findplus.service.install_watchdog", lambda *a, **k: None)

    result = CliRunner().invoke(main, ["start", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Now tracking all 1 device(s)." in result.output
    assert len(install_calls) == 1

    from findplus.db.models import Device
    from findplus.db.session import session_scope

    with session_scope() as s:
        assert s.get(Device, "TAG-1") is not None


# ------------------------------------------------------------- f: refresh fails
def test_start_refresh_failure_exits_1(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.providers.google_findhub.bootstrap.describe_stored_auth", lambda: {"exists": True}
    )

    def _raise(self):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "findplus.providers.google_findhub.client.FindHubClient.list_devices", _raise
    )
    install_calls: list[bool] = []
    monkeypatch.setattr("findplus.service.install", lambda *a, **k: install_calls.append(True))

    result = CliRunner().invoke(main, ["start"])
    assert result.exit_code == 1
    assert install_calls == []


# --------------------------------------------------- f2: apple refresh fails
def test_start_apple_refresh_failure_exits_1(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-C-E7 F3: branch B's Apple discovery gets the same guard as Google's."""
    monkeypatch.setattr(
        "findplus.providers.google_findhub.bootstrap.describe_stored_auth",
        lambda: {"exists": False},
    )
    settings = get_settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    (settings.state_dir / "apple-account.json").write_text("{}")

    def _raise(self):
        raise RuntimeError("session expired")

    monkeypatch.setattr(
        "findplus.providers.apple_findmy.provider.AppleFindMyProvider.list_devices", _raise
    )
    install_calls: list[bool] = []
    monkeypatch.setattr("findplus.service.install", lambda *a, **k: install_calls.append(True))

    result = CliRunner().invoke(main, ["start"])
    assert result.exit_code == 1, result.output
    assert "Could not list devices: session expired" in result.output
    assert install_calls == []


def _track_one_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.providers.google_findhub.bootstrap.describe_stored_auth", lambda: {"exists": True}
    )
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device
    from findplus.state import track_devices

    with session_scope() as s:
        upsert_device(s, "TAG-1", "Keys")
        track_devices(s, ["TAG-1"], exclusive=True)


# ------------------------------------------------------ g/h: install w/o --yes
def test_start_install_branch_without_yes_shows_plan(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _track_one_device(monkeypatch)
    monkeypatch.setattr("findplus.service.is_installed", lambda: False)
    install_calls: list[dict] = []
    watchdog_calls: list[dict] = []
    monkeypatch.setattr("findplus.service.install", lambda *a, **k: install_calls.append(k))
    monkeypatch.setattr(
        "findplus.service.install_watchdog", lambda *a, **k: watchdog_calls.append(k)
    )

    result = CliRunner().invoke(main, ["start"])
    assert result.exit_code == 0, result.output
    assert "Pass --yes" in result.output
    assert install_calls == []
    assert watchdog_calls == []


# ------------------------------------------------------------- i: start --yes
def test_start_yes_installs_confirmed(
    tmp_db, monkeypatch: pytest.MonkeyPatch, _no_browser: list[str]
) -> None:
    _track_one_device(monkeypatch)
    monkeypatch.setattr("findplus.service.is_installed", lambda: False)
    install_calls: list[dict] = []
    watchdog_calls: list[dict] = []
    monkeypatch.setattr("findplus.service.install", lambda *a, **k: install_calls.append(k))
    monkeypatch.setattr(
        "findplus.service.install_watchdog", lambda *a, **k: watchdog_calls.append(k)
    )

    result = CliRunner().invoke(main, ["start", "--yes"])
    assert result.exit_code == 0, result.output
    assert install_calls and install_calls[0]["confirmed"] is True
    assert watchdog_calls and watchdog_calls[0]["confirmed"] is True
    settings = get_settings()
    assert settings.base_url in _no_browser


# ------------------------------------------------ j: already installed -> start
def test_start_when_already_installed_calls_facade_start(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _track_one_device(monkeypatch)
    monkeypatch.setattr("findplus.service.is_installed", lambda: True)
    start_calls: list[bool] = []
    install_calls: list[bool] = []
    monkeypatch.setattr("findplus.service.start", lambda *a, **k: start_calls.append(True))
    monkeypatch.setattr("findplus.service.install", lambda *a, **k: install_calls.append(True))

    result = CliRunner().invoke(main, ["start", "--yes"])
    assert result.exit_code == 0, result.output
    assert start_calls == [True]
    assert install_calls == []


# ------------------------------------------------------------------------ stop
def test_stop_calls_facade_and_explains_next_steps(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.stop", lambda *a, **k: calls.append(True))
    result = CliRunner().invoke(main, ["stop"])
    assert result.exit_code == 0, result.output
    assert calls == [True]
    assert "uninstall --yes" in result.output
    assert "next login" in result.output


# --------------------------------------------------------------------- restart
def test_restart_calls_facade_restart_service(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_manager(monkeypatch, "launchd")
    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.restart_service", lambda: calls.append(True) or True)
    result = CliRunner().invoke(main, ["restart"])
    assert result.exit_code == 0, result.output
    assert calls == [True]


# ---------------------------------------------------------------------- status
def test_status_json_with_daemon_down_parses(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr("httpx.get", _raise)
    result = CliRunner().invoke(main, ["status", "--json"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert out["version"] is None
    assert out["lock_state"] == "unknown"


def test_status_falls_back_to_daemon_json_for_version(
    tmp_db, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Build-notes carry-forward #16: `port` fell back to daemon.json and
    `version` did not, so an unreachable daemon printed `version None` even
    with a daemon.json on disk recording the version it was started with."""

    def _raise(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr("httpx.get", _raise)
    from findplus.config import get_settings

    daemon_file = get_settings().daemon_file
    daemon_file.parent.mkdir(parents=True, exist_ok=True)
    daemon_file.write_text(
        json.dumps({"pid": 1, "port": 9999, "host": "127.0.0.1", "version": "1.0.0.dev0"})
    )
    try:
        result = CliRunner().invoke(main, ["status", "--json"])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["version"] == "1.0.0.dev0"
        assert out["port"] == 9999
    finally:
        daemon_file.unlink(missing_ok=True)


def test_status_text_has_service_and_watchdog_lines(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr("httpx.get", _raise)
    result = CliRunner().invoke(main, ["status"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert any(line.startswith("service") for line in lines)
    assert any(line.startswith("watchdog") for line in lines)


# ------------------------------------------------------------------- uninstall
def test_uninstall_without_yes_does_not_call_facade(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.uninstall", lambda *a, **k: calls.append(True))
    result = CliRunner().invoke(main, ["uninstall"])
    assert result.exit_code == 0, result.output
    assert "--yes" in result.output
    assert calls == []


def test_uninstall_yes_calls_both_facades(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("findplus.service.uninstall", lambda *a, **k: calls.append("uninstall"))
    monkeypatch.setattr(
        "findplus.service.uninstall_watchdog", lambda *a, **k: calls.append("watchdog")
    )
    result = CliRunner().invoke(main, ["uninstall", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls == ["uninstall", "watchdog"]

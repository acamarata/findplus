"""A machine without systemctl, launchctl or schtasks must still answer.

Purpose : Prove that every service-manager probe reports "not installed"
          instead of raising FileNotFoundError when its binary is absent.
          CI runs this suite on ubuntu, macOS and Windows images, and the
          python:3.12 container has no service manager at all, so
          `findplus status --json` used to exit 1 there with
          FileNotFoundError(2, 'systemctl').
Constraints: no real subprocess is spawned; the missing-binary branch is
          selected by patching shutil.which inside findplus.service._proc.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from findplus.cli.main import main
from findplus.service import _proc, launchd, schtasks, systemd


@pytest.fixture
def no_manager_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_proc.shutil, "which", lambda _name: None)


def test_run_reports_the_missing_binary_instead_of_raising(no_manager_binary) -> None:
    out = _proc.run(["definitely-not-installed", "--version"], capture=True)
    assert out.returncode == _proc.MISSING_BINARY_RC
    assert out.stdout == ""
    assert out.stderr == ""


def test_systemd_is_active_is_false_without_systemctl(no_manager_binary) -> None:
    assert systemd.is_active("findplus.service") is False


def test_launchd_is_loaded_is_false_without_launchctl(no_manager_binary) -> None:
    assert launchd.is_loaded("com.acamarata.findplus") is False


def test_schtasks_is_registered_is_false_without_schtasks(no_manager_binary) -> None:
    assert schtasks.is_registered("FindPlus") is False


@pytest.mark.parametrize("manager", ["launchd", "systemd", "schtasks"])
def test_status_json_exits_zero_on_every_manager_without_its_binary(
    tmp_db, monkeypatch: pytest.MonkeyPatch, no_manager_binary, manager: str
) -> None:
    def _raise(*_a, **_k):
        raise ConnectionError("refused")

    monkeypatch.setattr("httpx.get", _raise)
    monkeypatch.setattr("findplus.service.detect_manager", lambda: manager)
    monkeypatch.setattr("findplus.service.runtime.detect_manager", lambda: manager)
    monkeypatch.setattr("findplus.service.watchdog.detect_manager", lambda: manager)

    result = CliRunner().invoke(main, ["status", "--json"])

    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert out["loaded"] is False
    assert out["running"] is False

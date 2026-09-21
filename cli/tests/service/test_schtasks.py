"""Windows Task Scheduler backend: FindPlus-task.xml + watchdog switches
(P1-E7-W3-S1-T2).

Purpose : XML shape/snapshot, the watchdog's switches-only registration (no
          second XML file), and every schtasks.exe call mocked.
Constraints: Runs on any platform — `_task_xml` is pure, and every real
             subprocess.run call is mocked.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest

from findplus import service
from findplus.config import get_settings
from findplus.service import schtasks


def _patch_manager(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr("findplus.service.detect_manager", lambda: name)
    monkeypatch.setattr("findplus.service.runtime.detect_manager", lambda: name)
    monkeypatch.setattr("findplus.service.watchdog.detect_manager", lambda: name)


@pytest.fixture(autouse=True)
def _pretend_schtasks_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """service._proc skips a command whose binary is not installed, and
    schtasks.exe only exists on Windows. These tests assert the argv that
    would be issued, so the lookup is stubbed and subprocess.run mocked."""
    monkeypatch.setattr("findplus.service._proc.shutil.which", lambda name: f"/usr/bin/{name}")


# ------------------------------------------------------------------------- a
def test_plan_schtasks_unit_path_is_the_task_xml(tmp_db) -> None:
    settings = get_settings()
    p = schtasks.plan_schtasks(settings)
    assert p.unit_path == settings.task_xml_path
    assert p.unit_path.name == "FindPlus-task.xml"


# ------------------------------------------------------------------------- b
def test_plan_schtasks_unit_text_shape(tmp_db) -> None:
    settings = get_settings()
    text = schtasks.plan_schtasks(settings).unit_text
    assert text.startswith('<?xml version="1.0" encoding="UTF-16"?>')
    assert "-m findplus.cli" in text
    assert "serve --foreground" in text.split("<Arguments>")[1]


# ------------------------------------------------------------------------- c
def test_plan_schtasks_unit_text_parses_as_utf16(tmp_db) -> None:
    settings = get_settings()
    text = schtasks.plan_schtasks(settings).unit_text
    ET.fromstring(text.encode("utf-16"))  # must not raise


# ------------------------------------------------------------------------- c2
def test_plan_schtasks_execution_time_limit_is_unlimited(tmp_db) -> None:
    """PT1H killed the daemon every hour (blind B4); PT0S means no limit."""
    settings = get_settings()
    text = schtasks.plan_schtasks(settings).unit_text
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in text
    assert "PT1H" not in text


# ------------------------------------------------------------------------- d
def test_plan_schtasks_program_override_verbatim(tmp_db) -> None:
    settings = get_settings()
    program = r"C:\Program Files\findplus-daemon.exe"
    text = schtasks.plan_schtasks(settings, program=program).unit_text
    assert f"<Command>{program}</Command>" in text


# ------------------------------------------------------------------------- e
def test_plan_schtasks_load_command(tmp_db) -> None:
    settings = get_settings()
    p = schtasks.plan_schtasks(settings)
    assert p.load_command == [
        "schtasks",
        "/Create",
        "/TN",
        "FindPlus",
        "/XML",
        str(settings.task_xml_path),
        "/F",
    ]


# ------------------------------------------------------------------------- f
def test_watchdog_plan_schtasks_switches_only(tmp_db) -> None:
    settings = get_settings()
    p = schtasks.watchdog_plan_schtasks(settings)
    for token in ("/SC", "MINUTE", "/MO", "5", "/TN", "FindPlusWatchdog"):
        assert token in p.load_command
    assert p.unload_command == ["schtasks", "/Delete", "/TN", "FindPlusWatchdog", "/F"]
    assert p.unit_text == ""


# ------------------------------------------------------------------------- g
def test_install_watchdog_writes_no_second_xml(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_manager(monkeypatch, "schtasks")
    settings = get_settings()
    with patch("subprocess.run") as run:
        service.install_watchdog(settings, confirmed=True)
    assert not any("FindPlusWatchdog-task.xml" in str(c) for c in run.call_args_list)
    assert not settings.task_xml_path.exists()


# ------------------------------------------------------------------------- h
def test_facade_install_writes_xml_and_creates_task(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_manager(monkeypatch, "schtasks")
    settings = get_settings()
    with patch("subprocess.run") as run:
        service.install(settings, confirmed=True)
    assert settings.task_xml_path.exists()
    ET.fromstring(settings.task_xml_path.read_bytes())  # parses cleanly
    create_calls = [c for c in run.call_args_list if "/Create" in c.args[0]]
    assert len(create_calls) == 1
    assert "FindPlus" in create_calls[0].args[0]


# ------------------------------------------------------------------------- i
def test_facade_uninstall_deletes_both_tasks_and_xml(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_manager(monkeypatch, "schtasks")
    settings = get_settings()
    settings.ensure_state_dir()
    settings.task_xml_path.write_text("x", encoding="utf-8")
    with patch("subprocess.run") as run:
        service.uninstall(settings)
    deleted_names = [c.args[0][3] for c in run.call_args_list if "/Delete" in c.args[0]]
    assert "FindPlus" in deleted_names
    assert "FindPlusWatchdog" in deleted_names
    assert not settings.task_xml_path.exists()


# ------------------------------------------------------------------------- j
def test_facade_stop_ends_both_tasks_keeps_xml(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_manager(monkeypatch, "schtasks")
    settings = get_settings()
    settings.ensure_state_dir()
    settings.task_xml_path.write_text("x", encoding="utf-8")
    with patch("subprocess.run") as run:
        service.stop(settings)
    ended_names = [c.args[0][3] for c in run.call_args_list if "/End" in c.args[0]]
    assert "FindPlus" in ended_names
    assert "FindPlusWatchdog" in ended_names
    assert settings.task_xml_path.exists()


# ------------------------------------------------------------------------- k
def test_detect_manager_routes_by_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    from findplus.service.plan import detect_manager

    monkeypatch.setattr("platform.system", lambda: "Windows")
    assert detect_manager() == "schtasks"
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    assert detect_manager() == "launchd"
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert detect_manager() == "systemd"


# ------------------------------------------------------------------------- l
def test_is_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        def __init__(self, code: int) -> None:
            self.returncode = code

    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Result(0))
    assert schtasks.is_registered("FindPlus") is True
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Result(1))
    assert schtasks.is_registered("FindPlus") is False

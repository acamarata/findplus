"""Facade dispatch and the pinned plan()/watchdog_plan() shapes.

Every unit path starts at Path.home() and no plan ever shells out with sudo
(specs/service-package.md § Rules). Split out of test_service_cmds.py, which
was 378 lines (PRI hard rule 7 applies to test files too).
"""

from __future__ import annotations

import plistlib

import pytest

from findplus import service
from findplus.config import get_settings
from tests.service._helpers import patch_manager as _patch_manager


# --------------------------------------------------- o: unsupported-platform raise
# NOTE deviation from the ticket text: as literally written, case (o) monkeypatches
# detect_manager -> "schtasks" and expects RuntimeError. That held only before
# P1-E7-W3-S1-T2 landed; since T1 and T2 were built in the same pass here, schtasks
# is fully implemented by the time this suite runs. The still-real RuntimeError
# branch is the genuinely-unsupported-platform case, so it is tested here instead;
# schtasks dispatch itself is covered by test_schtasks.py (T2).
def test_facade_raises_on_unsupported_platform(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_manager(monkeypatch, "unsupported")
    with pytest.raises(RuntimeError):
        service.stop()
    with pytest.raises(RuntimeError):
        service.start()
    with pytest.raises(RuntimeError):
        service.restart()
    with pytest.raises(RuntimeError):
        service.status()


# ----------------------------------------------------------------- p/s: launchd
def test_plan_snapshot_launchd(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_manager(monkeypatch, "launchd")
    settings = get_settings()
    payload = plistlib.loads(service.plan(settings).unit_text.encode())
    assert payload["Label"] == "com.acamarata.findplus"
    assert payload["RunAtLoad"] is True
    assert "KeepAlive" in payload


def test_watchdog_plan_snapshot_launchd(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_manager(monkeypatch, "launchd")
    settings = get_settings()
    payload = plistlib.loads(service.watchdog_plan(settings).unit_text.encode())
    assert payload["StartInterval"] == 300


# ------------------------------------------------------------------- q: systemd
def test_plan_snapshot_systemd(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_manager(monkeypatch, "systemd")
    settings = get_settings()
    text = service.plan(settings).unit_text
    assert "Type=simple" in text
    assert "WantedBy=default.target" in text


# ------------------------------------------------------------------ r: schtasks
def test_plan_snapshot_schtasks(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_manager(monkeypatch, "schtasks")
    settings = get_settings()
    text = service.plan(settings).unit_text
    assert "serve --foreground" in text


# --------------------------------------------------------------- t: path-home
def test_plan_paths_are_under_home(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    settings = get_settings()
    for name in ("launchd", "systemd"):
        _patch_manager(monkeypatch, name)
        assert str(service.plan(settings).unit_path).startswith(str(Path.home()))
        assert str(service.watchdog_plan(settings).unit_path).startswith(str(Path.home()))

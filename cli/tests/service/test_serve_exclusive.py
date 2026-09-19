"""`serve` refuses a second daemon via the daemon.json probe (P1-E7-W3-S1-T5).

Purpose : _check_exclusive's decision table (live findplus / locked / foreign
          service / stale / missing / malformed) and the serve command's
          exit-3 guard.
Constraints: httpx.get is always monkeypatched; nothing touches the network.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from findplus.cli.cmd_service import _check_exclusive, serve
from findplus.config import get_settings


class _Resp:
    def __init__(self, code: int, body: dict | None = None) -> None:
        self.status_code = code
        self._body = body or {}

    def json(self) -> dict:
        return self._body


# ------------------------------------------------------------------------- a
def test_no_daemon_json_returns_false(tmp_db) -> None:
    settings = get_settings()
    assert _check_exclusive(settings.state_dir) == (False, "")


def _write(settings, payload) -> None:
    settings.ensure_state_dir()
    settings.daemon_file.write_text(
        json.dumps(payload) if not isinstance(payload, str) else payload
    )


# ------------------------------------------------------------------------- b
def test_findplus_running_returns_true(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    _write(settings, {"port": 8647, "host": "127.0.0.1"})
    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp(200, {"app": "findplus"}))
    assert _check_exclusive(settings.state_dir) == (True, "http://127.0.0.1:8647/")


# ------------------------------------------------------------------------- c
def test_locked_daemon_401_returns_true(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    _write(settings, {"port": 8647, "host": "127.0.0.1"})
    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp(401))
    assert _check_exclusive(settings.state_dir) == (True, "http://127.0.0.1:8647/")


# ------------------------------------------------------------------------- d
def test_foreign_service_returns_false(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    _write(settings, {"port": 8647, "host": "127.0.0.1"})
    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp(200, {"app": "other_app"}))
    assert _check_exclusive(settings.state_dir) == (False, "")


# ------------------------------------------------------------------------- e
def test_connection_refused_returns_false(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    _write(settings, {"port": 8647, "host": "127.0.0.1"})

    def _raise(*a, **k):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr("httpx.get", _raise)
    assert _check_exclusive(settings.state_dir) == (False, "")


# ------------------------------------------------------------------------- f
def test_invalid_json_returns_false(tmp_db) -> None:
    settings = get_settings()
    _write(settings, "{not json")
    assert _check_exclusive(settings.state_dir) == (False, "")


# ------------------------------------------------------------------------- g
def test_missing_port_key_returns_false(tmp_db) -> None:
    settings = get_settings()
    _write(settings, {"pid": 1})
    assert _check_exclusive(settings.state_dir) == (False, "")


# ------------------------------------------------------------------------- h
def test_serve_exits_3_when_already_running(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.cli.cmd_serve._check_exclusive",
        lambda state_dir: (True, "http://127.0.0.1:8647/"),
    )
    result = CliRunner().invoke(serve, ["--foreground"])
    assert result.exit_code == 3
    assert "already running" in result.output
    assert "http://127.0.0.1:8647/" in result.output

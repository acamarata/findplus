"""Watchdog probe: daemon.json port wins on mismatch, 401 stays healthy
(P1-E7-W3-S1-T3).

Purpose : check_once port selection (daemon.json overrides settings.port,
          with a logged mismatch) and the 401-is-healthy / restart-on-wedged
          behavior of restart_if_wedged.
Constraints: urllib.request.urlopen is always monkeypatched; nothing touches
             the network or the real ~/.findplus.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from findplus.config import get_settings
from findplus.service import watchdog as watchdog_module


class _StubLog:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def warning(self, event: str, **kw) -> None:
        self.calls.append(("warning", event, kw))

    def info(self, event: str, **kw) -> None:
        self.calls.append(("info", event, kw))

    def error(self, event: str, **kw) -> None:
        self.calls.append(("error", event, kw))


@pytest.fixture(autouse=True)
def _log(monkeypatch: pytest.MonkeyPatch) -> _StubLog:
    stub = _StubLog()
    monkeypatch.setattr(watchdog_module, "log", stub)
    return stub


class _Response:
    def __init__(self, status: int, body: bytes = b'{"app": "findplus"}') -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _write_daemon_json(settings, payload) -> None:
    settings.ensure_state_dir()
    settings.daemon_file.write_text(json.dumps(payload) if payload is not None else "not json")


# --------------------------------------------------------------------- a/b
def test_check_once_no_daemon_json_probes_settings_port(
    tmp_db, monkeypatch: pytest.MonkeyPatch, _log: _StubLog
) -> None:
    settings = get_settings()
    seen: list[str] = []

    def _urlopen(url, timeout=10):
        seen.append(url)
        return _Response(200)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    ok, detail = watchdog_module.check_once(settings)
    assert (ok, detail) == (True, "ok")
    assert seen == [f"http://{settings.host}:{settings.port}/api/health"]
    assert not any(c[1] == "watchdog_port_mismatch" for c in _log.calls)


def test_check_once_daemon_json_equal_port_no_warning(
    tmp_db, monkeypatch: pytest.MonkeyPatch, _log: _StubLog
) -> None:
    settings = get_settings()
    _write_daemon_json(settings, {"port": settings.port})
    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=10: _Response(200))
    ok, _ = watchdog_module.check_once(settings)
    assert ok is True
    assert not any(c[1] == "watchdog_port_mismatch" for c in _log.calls)


# ----------------------------------------------------------------------- c
def test_check_once_port_mismatch_probes_daemon_port_and_warns(
    tmp_db, monkeypatch: pytest.MonkeyPatch, _log: _StubLog
) -> None:
    settings = get_settings()
    _write_daemon_json(settings, {"port": 9000})
    seen: list[str] = []

    def _urlopen(url, timeout=10):
        seen.append(url)
        return _Response(200)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    ok, _ = watchdog_module.check_once(settings)
    assert ok is True
    assert seen == [f"http://{settings.host}:9000/api/health"]
    warnings = [c for c in _log.calls if c[1] == "watchdog_port_mismatch"]
    assert warnings == [
        ("warning", "watchdog_port_mismatch", {"settings_port": settings.port, "daemon_port": 9000})
    ]


# --------------------------------------------------------------------- d/e/f
def test_check_once_malformed_daemon_json_falls_back(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    _write_daemon_json(settings, None)  # writes literal "not json"
    seen: list[str] = []
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda url, timeout=10: (seen.append(url), _Response(200))[1]
    )
    ok, _ = watchdog_module.check_once(settings)
    assert ok is True
    assert seen == [f"http://{settings.host}:{settings.port}/api/health"]


def test_check_once_daemon_json_missing_port_falls_back(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    _write_daemon_json(settings, {"pid": 1})
    seen: list[str] = []
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda url, timeout=10: (seen.append(url), _Response(200))[1]
    )
    watchdog_module.check_once(settings)
    assert seen == [f"http://{settings.host}:{settings.port}/api/health"]


def test_check_once_daemon_json_non_int_port_falls_back(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    _write_daemon_json(settings, {"port": "abc"})
    seen: list[str] = []
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda url, timeout=10: (seen.append(url), _Response(200))[1]
    )
    watchdog_module.check_once(settings)
    assert seen == [f"http://{settings.host}:{settings.port}/api/health"]


# ----------------------------------------------------------------------- g
def test_check_once_401_is_healthy_and_no_restart(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()

    def _raise_401(url, timeout=10):
        raise urllib.error.HTTPError(url, 401, "locked", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _raise_401)
    ok, detail = watchdog_module.check_once(settings)
    assert (ok, detail) == (True, "locked but responding")

    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.restart_service", lambda: calls.append(True) or True)
    result = watchdog_module.restart_if_wedged(settings)
    assert calls == []
    assert "locked but responding" in result


# ----------------------------------------------------------------------- h
def test_check_once_foreign_app_unhealthy_restarts(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda url, timeout=10: _Response(200, b'{"app": "other"}'),
    )
    ok, detail = watchdog_module.check_once(settings)
    assert (ok, detail) == (False, "port used by a different service")

    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.restart_service", lambda: calls.append(True) or True)
    result = watchdog_module.restart_if_wedged(settings)
    assert calls == [True]
    assert result.startswith("restarted")


# ----------------------------------------------------------------------- i
def test_check_once_url_error_restarts(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()

    def _raise(url, timeout=10):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    ok, _ = watchdog_module.check_once(settings)
    assert ok is False

    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.restart_service", lambda: calls.append(True) or True)
    watchdog_module.restart_if_wedged(settings)
    assert calls == [True]

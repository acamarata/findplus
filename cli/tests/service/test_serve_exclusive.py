"""`serve` refuses a second daemon via the daemon.json probe (P1-E7-W3-S1-T5).

Purpose : _check_exclusive's decision table (live findplus / locked / foreign
          service / stale / missing / malformed) and the serve command's
          exit-3 guard.
Constraints: httpx.get is always monkeypatched; nothing touches the network.
"""

from __future__ import annotations

import json
import os

import pytest
from click.testing import CliRunner

from findplus.cli.cmd_serve import _bind_or_exit
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


class _FakeServer:
    """Stands in for uvicorn.Server in test_serve_starts_and_joins_a_retention_thread:
    `run()` blocks on `stop_server` instead of actually binding a socket."""

    should_exit = False
    install_signal_handlers = True

    def __init__(self, config) -> None:
        pass

    def run(self) -> None:
        self.stop.wait(timeout=10)


# ------------------------------------------------------------- i: retention
def test_serve_starts_and_joins_a_retention_thread(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """The daily prune runs beside the poller and is joined on shutdown."""
    import threading

    from findplus.service.retention import RetentionScheduler

    running = threading.Event()
    released = threading.Event()

    def _fake_run_forever(self) -> None:
        running.set()
        released.wait(timeout=10)

    monkeypatch.setattr(RetentionScheduler, "run_forever", _fake_run_forever)
    monkeypatch.setattr(RetentionScheduler, "stop", lambda self: released.set())

    stop_server = threading.Event()
    _FakeServer.stop = stop_server
    monkeypatch.setattr("uvicorn.Server", _FakeServer)
    monkeypatch.setattr("findplus.cli.cmd_serve._wait_for_stop", lambda ev, th: 0)
    # signal.signal only works on the main thread, and serve() runs on another
    # one here so the test can watch it while it is up.
    monkeypatch.setattr("signal.signal", lambda *a, **k: None)

    serve_thread = threading.Thread(
        target=lambda: CliRunner().invoke(serve, ["--foreground", "--no-poller"]),
        daemon=True,
    )
    serve_thread.start()

    assert running.wait(timeout=10), "the retention thread never started"
    assert any(t.name == "retention" for t in threading.enumerate())

    stop_server.set()
    serve_thread.join(timeout=15)

    assert not serve_thread.is_alive(), "serve() did not return"
    assert released.is_set(), "retention.stop() was never called"
    assert not any(t.name == "retention" for t in threading.enumerate())


# --------------------------------------------------- j: port/host resolution
# Closeout C-M1: OriginGuardMiddleware no longer re-reads get_settings() per
# request -- it reads app.state.bound_host/bound_port, set once by
# create_app(bound_host=, bound_port=) at startup (_start_uvicorn). A
# --port/--host override therefore only has to reach _bind_or_exit's return
# value; it used to also have to land in FINDPLUS_PORT/FINDPLUS_HOST via a
# direct (non-monkeypatch) os.environ write, which is exactly what leaked
# FINDPLUS_PORT=8641 out of test_sigterm.py's CliRunner invocation into every
# test that ran afterward in the same process (CF-P2-3 follow-up). These
# cases now pin the opposite: _bind_or_exit touches neither os.environ nor
# get_settings()'s own return value.
def test_bind_or_exit_resolves_a_port_override_without_touching_the_environment(
    tmp_db,
) -> None:
    assert "FINDPLUS_PORT" not in os.environ
    default_port = get_settings().port
    _bind_host, bind_port = _bind_or_exit(None, 19999)
    assert bind_port == 19999
    assert "FINDPLUS_PORT" not in os.environ
    assert get_settings().port == default_port


def test_bind_or_exit_resolves_a_host_override_without_touching_the_environment(
    tmp_db,
) -> None:
    assert "FINDPLUS_HOST" not in os.environ
    default_host = get_settings().host
    bind_host, _bind_port = _bind_or_exit("127.0.0.1", None)
    assert bind_host == "127.0.0.1"
    assert "FINDPLUS_HOST" not in os.environ
    assert get_settings().host == default_host


def test_bind_or_exit_leaves_settings_untouched_with_no_override(tmp_db) -> None:
    assert "FINDPLUS_PORT" not in os.environ
    assert "FINDPLUS_HOST" not in os.environ
    default_port = get_settings().port
    _bind_or_exit(None, None)
    assert "FINDPLUS_PORT" not in os.environ
    assert "FINDPLUS_HOST" not in os.environ
    assert get_settings().port == default_port

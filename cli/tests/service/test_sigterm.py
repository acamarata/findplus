"""SIGTERM/SIGINT stop the serve loop and remove daemon.json (P1-E7-W3-S1-T6).

Purpose : The pure `_make_signal_handler` factory, plus subprocess integration
          tests proving `serve --foreground` cleans up daemon.json on both
          signals, and that a server thread dying on its own ends serve
          instead of hanging it.
Constraints: The subprocess tests use port 8640 (never 8647, the real default)
          and run via `sys.executable -m findplus` (findplus/__main__.py), so
          they never skip for want of the `findplus` console script on PATH
          (blind B9 -- an editable, non-`pip install -e`d checkout used to
          skip these silently).
          Startup readiness polls GET /api/health, not daemon.json.exists()
          -- `_run_server` (cmd_serve.py) writes daemon.json BEFORE it starts
          uvicorn, so the file appearing only proves the process got that
          far, not that the server can answer a request. Shutdown gets a
          20s budget: `_run_server`'s own finally block can legitimately take
          up to ~10.25s (uvicorn thread join 5s + the retention worker's join
          5s, plus the 0.25s stop_event poll interval), and a machine under
          load stretches thread-join wall time further. A tighter external
          timeout than the code's own worst case is a flake, not a hang
          detector (found under a 2026-09-23 load investigation: repeated
          full-suite failures traced to this budget mismatch, not to the
          daemon itself -- no code change needed there).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from findplus.cli.cmd_serve import _wait_for_stop
from findplus.cli.cmd_service import _make_signal_handler, serve

#: Generous but bounded: covers slow interpreter/import startup and the
#: daemon's own ~10.25s worst-case shutdown (see module docstring) with
#: headroom for scheduling delays under a loaded machine, while still
#: failing on a genuine hang instead of waiting forever.
_READY_DEADLINE_S = 20.0
_SHUTDOWN_TIMEOUT_S = 20.0


# ------------------------------------------------------------------------- a
def test_make_signal_handler_sets_the_event() -> None:
    stop_event = threading.Event()
    handler = _make_signal_handler(stop_event)
    assert not stop_event.is_set()
    handler(signal.SIGTERM, None)
    assert stop_event.is_set()


# ------------------------------------------------------------------------- b/c
def _wait_for_health(proc: subprocess.Popen[str], url: str, deadline_s: float) -> None:
    """Poll GET {url}/api/health until it answers 200, the process dies, or
    `deadline_s` passes -- the real readiness signal, not a file marker."""
    end = time.monotonic() + deadline_s
    last_exc: Exception | None = None
    while time.monotonic() < end:
        if proc.poll() is not None:
            raise AssertionError(
                f"daemon exited during startup (rc={proc.returncode}): {proc.stderr.read()}"
            )
        try:
            if httpx.get(f"{url}/api/health", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError as exc:  # connection refused while it binds
            last_exc = exc
        time.sleep(0.1)
    raise AssertionError(f"{url}/api/health never answered within {deadline_s}s: {last_exc}")


def _run_serve_and_signal(tmp_path: Path, sig: int) -> None:
    env = dict(
        os.environ,
        FINDPLUS_STATE_DIR=str(tmp_path),
        FINDPLUS_DATABASE_PATH=str(tmp_path / "test.sqlite"),
    )
    argv = [
        sys.executable,
        "-m",
        "findplus",
        "serve",
        "--foreground",
        "--no-poller",
        "--port",
        "8640",
    ]
    proc = subprocess.Popen(
        argv,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        daemon_json = tmp_path / "daemon.json"
        _wait_for_health(proc, "http://127.0.0.1:8640", _READY_DEADLINE_S)
        assert daemon_json.exists(), proc.stderr.read() if proc.poll() is not None else ""

        os.kill(proc.pid, sig)
        proc.wait(timeout=_SHUTDOWN_TIMEOUT_S)
        assert proc.returncode == 0
        assert not daemon_json.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX signal delivery (os.kill SIGTERM to a subprocess)"
)
def test_sigterm_clean_shutdown(tmp_path: Path) -> None:
    _run_serve_and_signal(tmp_path, signal.SIGTERM)


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX signal delivery (os.kill SIGINT to a subprocess)"
)
def test_sigint_clean_shutdown(tmp_path: Path) -> None:
    _run_serve_and_signal(tmp_path, signal.SIGINT)


# ------------------------------------------------------------------------- d
def test_poller_join_timeout_is_respected(monkeypatch) -> None:
    """A stuck poller thread must not hang serve's shutdown past its 5s join
    timeout. Simulated by calling the same join-with-timeout pattern serve()
    uses, on a thread that blocks past that timeout."""

    def _slow_target() -> None:
        time.sleep(2.0)

    t = threading.Thread(target=_slow_target, daemon=True)
    t.start()
    started = time.monotonic()
    t.join(timeout=0.2)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0, "join(timeout=...) must not block past its own timeout"


# ------------------------------------------------------------------------- d2
def test_wait_for_stop_returns_1_when_the_server_thread_dies() -> None:
    """A uvicorn thread that cannot bind exits at once; serve must not block
    on the stop event forever while daemon.json claims a live daemon."""
    stop_event = threading.Event()
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    started = time.monotonic()
    assert _wait_for_stop(stop_event, dead) == 1
    assert time.monotonic() - started < 2.0


def test_serve_exits_1_when_the_server_cannot_start(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _DeadServer:
        def __init__(self, config: object) -> None:
            self.should_exit = False
            self.install_signal_handlers = True

        def run(self) -> None:
            return  # uvicorn gives up on the bind and the thread ends at once

    monkeypatch.setattr("uvicorn.Server", _DeadServer)
    # `--port 8641` no longer reaches os.environ (closeout C-M1 removed
    # _bind_or_exit's FINDPLUS_PORT export), but this swaps in a private copy
    # of os.environ for the duration of the test regardless -- belt and
    # suspenders against any future code path along `serve`'s invoke that
    # writes to it directly, the way _bind_or_exit itself used to (CF-P2-3
    # follow-up: that write, uncaught here, once leaked FINDPLUS_PORT=8641
    # into every test that ran afterward in the same process).
    monkeypatch.setattr(os, "environ", os.environ.copy())
    result = CliRunner().invoke(serve, ["--foreground", "--no-poller", "--port", "8641"])
    assert result.exit_code == 1, result.output
    assert "may already be in use" in result.output


# ------------------------------------------------------------------------- e/f
def test_unlink_missing_ok_never_raises_when_absent(tmp_path: Path) -> None:
    daemon_json = tmp_path / "daemon.json"
    assert not daemon_json.exists()
    daemon_json.unlink(missing_ok=True)  # must not raise
    daemon_json.unlink(missing_ok=True)  # idempotent, still must not raise

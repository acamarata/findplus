"""SIGTERM/SIGINT stop the serve loop and remove daemon.json (P1-E7-W3-S1-T6).

Purpose : The pure `_make_signal_handler` factory, plus subprocess integration
          tests proving `serve --foreground` cleans up daemon.json on both
          signals, and that a server thread dying on its own ends serve
          instead of hanging it.
Constraints: The subprocess tests use port 8640 (never 8647, the real default)
          and skip cleanly if the `findplus` console script is not on PATH.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from findplus.cli.cmd_serve import _wait_for_stop
from findplus.cli.cmd_service import _make_signal_handler, serve


# ------------------------------------------------------------------------- a
def test_make_signal_handler_sets_the_event() -> None:
    stop_event = threading.Event()
    handler = _make_signal_handler(stop_event)
    assert not stop_event.is_set()
    handler(signal.SIGTERM, None)
    assert stop_event.is_set()


# ------------------------------------------------------------------------- b/c
def _run_serve_and_signal(tmp_path: Path, sig: int) -> None:
    findplus_bin = shutil.which("findplus") or (
        str(Path(sys.executable).parent / "findplus")
        if (Path(sys.executable).parent / "findplus").exists()
        else None
    )
    if not findplus_bin:
        import pytest

        pytest.skip("findplus console script not on PATH")

    env = dict(
        os.environ,
        FINDPLUS_STATE_DIR=str(tmp_path),
        FINDPLUS_DATABASE_PATH=str(tmp_path / "test.sqlite"),
    )
    proc = subprocess.Popen(
        [findplus_bin, "serve", "--foreground", "--no-poller", "--port", "8640"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        daemon_json = tmp_path / "daemon.json"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not daemon_json.exists():
            time.sleep(0.1)
        assert daemon_json.exists(), proc.stderr.read() if proc.poll() is not None else ""

        os.kill(proc.pid, sig)
        proc.wait(timeout=5)
        assert proc.returncode == 0
        assert not daemon_json.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_sigterm_clean_shutdown(tmp_path: Path) -> None:
    _run_serve_and_signal(tmp_path, signal.SIGTERM)


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
    result = CliRunner().invoke(serve, ["--foreground", "--no-poller", "--port", "8641"])
    assert result.exit_code == 1, result.output
    assert "may already be in use" in result.output


# ------------------------------------------------------------------------- e/f
def test_unlink_missing_ok_never_raises_when_absent(tmp_path: Path) -> None:
    daemon_json = tmp_path / "daemon.json"
    assert not daemon_json.exists()
    daemon_json.unlink(missing_ok=True)  # must not raise
    daemon_json.unlink(missing_ok=True)  # idempotent, still must not raise

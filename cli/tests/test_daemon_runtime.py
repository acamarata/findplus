"""daemon.json I/O and daemon_alive() health-checking."""

from __future__ import annotations

import json
import os

from findplus.service.runtime import daemon_alive, read_daemon_file, write_daemon_file


def test_stale_pid_not_alive(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path))
    (tmp_path / "daemon.json").write_text(
        json.dumps({"pid": 1, "port": 59999, "host": "127.0.0.1"})
    )
    assert not daemon_alive()


def test_missing_file_not_alive(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path))
    assert not daemon_alive()


def test_write_read_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path))
    write_daemon_file(pid=os.getpid(), port=18647, host="127.0.0.1", version="test", argv=["test"])
    data = read_daemon_file()
    assert data["pid"] == os.getpid()
    assert (tmp_path / "daemon.json").stat().st_mode & 0o777 == 0o600

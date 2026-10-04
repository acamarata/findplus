"""secrets.json writes are atomic and serialised across processes (O15).

The vendored token_cache truncates and rewrites in place. A CLI `auth` run racing
the daemon could read a half-written file (has_google_session() flickering false)
or drop the other process's key. These tests pin the replacement write path.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from findplus.providers.google_findhub import secrets_store

_WRITER = """
import sys
from pathlib import Path
from findplus.providers.google_findhub import secrets_store
path, prefix, count = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
for i in range(count):
    secrets_store.set_value(path, f"{prefix}{i}", "x" * 2000)
"""


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_set_value_merges_and_creates_the_file(tmp_path: Path) -> None:
    path = tmp_path / "state" / "secrets.json"
    secrets_store.set_value(path, "a", 1)
    secrets_store.set_value(path, "b", "two")
    assert json.loads(path.read_text()) == {"a": 1, "b": "two"}


def test_set_value_repairs_an_empty_file_but_refuses_a_corrupt_one(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text("")
    secrets_store.set_value(path, "a", 1)
    assert json.loads(path.read_text()) == {"a": 1}
    path.write_text("{not json")
    with pytest.raises(RuntimeError, match="Could not read secrets file"):
        secrets_store.set_value(path, "b", 2)
    assert path.read_text() == "{not json"  # left for the owner, not reset


@pytest.mark.posix_only
def test_temp_file_and_result_are_private_and_no_temp_is_left(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    path = state / "secrets.json"
    original = os.umask(0o000)
    try:
        secrets_store.set_value(path, "aas_token", "t")
    finally:
        os.umask(original)
    assert _mode(path) == 0o600
    assert _mode(secrets_store.lock_path(path)) == 0o600
    assert [p.name for p in state.iterdir() if p.name.endswith(".tmp")] == []


def test_a_failed_write_leaves_the_old_file_intact(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "secrets.json"
    secrets_store.set_value(path, "keep", "me")

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(secrets_store.os, "replace", boom)
    with pytest.raises(OSError):
        secrets_store.set_value(path, "new", "value")
    assert json.loads(path.read_text()) == {"keep": "me"}
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_threads_do_not_drop_each_others_keys(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"

    def run(prefix: str) -> None:
        for i in range(25):
            secrets_store.set_value(path, f"{prefix}{i}", i)

    threads = [threading.Thread(target=run, args=(f"t{n}_",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(json.loads(path.read_text())) == 100


def test_two_processes_never_drop_a_key_and_a_reader_never_sees_a_partial_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "secrets.json"
    secrets_store.set_value(path, "seed", "s")
    procs = [
        subprocess.Popen([sys.executable, "-c", _WRITER, str(path), f"p{n}_", "40"])
        for n in range(2)
    ]
    partial = 0
    while any(p.poll() is None for p in procs):
        try:
            json.loads(path.read_text())
        except json.JSONDecodeError:
            partial += 1
    for p in procs:
        assert p.wait(timeout=60) == 0
    data = json.loads(path.read_text())
    assert partial == 0
    assert len(data) == 1 + 2 * 40
    assert data["seed"] == "s"


def test_the_lock_is_reentrant_in_one_thread(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    with secrets_store.locked(path):
        secrets_store.set_value(path, "inner", 1)
    assert json.loads(path.read_text()) == {"inner": 1}


def test_the_patched_vendor_hook_goes_through_the_atomic_store(tmp_path: Path, monkeypatch) -> None:
    """set_cached_value (what the vendor calls) lands in the state dir via set_value."""
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path))
    from findplus.config import get_settings
    from findplus.providers.google_findhub import bootstrap

    calls: list[tuple[str, object]] = []
    real = secrets_store.set_value
    monkeypatch.setattr(
        secrets_store, "set_value", lambda p, n, v: (calls.append((n, v)), real(p, n, v))[1]
    )
    import types

    fake = types.SimpleNamespace(
        _get_secrets_file=None, set_cached_value=None, get_cached_value=lambda name: None
    )
    bootstrap._patch_token_cache(fake)
    fake.set_cached_value("aas_token", "tok")
    assert calls == [("aas_token", "tok")]

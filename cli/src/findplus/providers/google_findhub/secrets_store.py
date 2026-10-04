"""Atomic, cross-process-safe writes of the Google `secrets.json`.

Purpose : The vendored `Auth.token_cache.set_cached_value` reads the file, then
          truncates and rewrites it in place. A reader (the daemon's
          `has_google_session`, or a CLI `auth` run) landing in between saw half a
          file, and two writers in different processes could drop each other's key.
Inputs  : the secrets path, a key and a value.
Outputs : `set_value` merges one key into the JSON object; `locked` is the
          exclusive section both it and any read-modify-write caller share.
Constraints:
    - The temp file is created in the SAME 0700 directory with mode 0600, fsynced,
      then os.replace()d, so a reader sees the old file or the new one, never a
      partial one, and the tokens are never on disk at the process umask.
    - Cross-process lock: fcntl.flock on `secrets.json.lock` (POSIX), msvcrt.locking
      on Windows. The lock file holds no secret and is 0600 like its neighbour.
    - Vendor code is not edited; bootstrap rebinds `set_cached_value` to `set_value`.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

#: Serialises threads in this process (flock is per open-file, not per thread).
_thread_lock = threading.RLock()
_depth = threading.local()
LOCK_TIMEOUT_S = 10.0


def lock_path(path: Path) -> Path:
    """The lock file that guards `path`."""
    return path.with_name(path.name + ".lock")


def _open_lock(path: Path) -> int:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return os.open(lock_path(path), os.O_RDWR | os.O_CREAT, 0o600)


def _acquire(fd: int) -> None:
    """Take the exclusive OS lock on `fd`, waiting up to LOCK_TIMEOUT_S."""
    if os.name == "nt":  # pragma: no cover - exercised by the Windows CI lane
        import msvcrt

        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
                return
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
    import fcntl

    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.02)


def _release(fd: int) -> None:
    with contextlib.suppress(OSError):
        if os.name == "nt":  # pragma: no cover
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """Exclusive section over `path` for this process (threads) and others. Re-entrant."""
    with _thread_lock:
        depth = getattr(_depth, "n", 0)
        if depth:
            _depth.n = depth + 1
            try:
                yield
            finally:
                _depth.n -= 1
            return
        fd = _open_lock(path)
        try:
            _acquire(fd)
            _depth.n = 1
            try:
                yield
            finally:
                _depth.n = 0
        finally:
            _release(fd)


def atomic_write_json(path: Path, data: dict[str, object]) -> None:
    """Write `data` to `path` via a 0600 temp file in the same dir, fsync, os.replace."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        _replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def _replace(src: Path, dst: Path) -> None:
    """os.replace, retried briefly: Windows refuses while a reader holds the file open."""
    for attempt in range(20):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 19:
                raise
            time.sleep(0.05)


def _read_text(path: Path) -> str:
    """read_text, retried briefly: Windows refuses to open a file mid-os.replace."""
    for attempt in range(20):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            if os.name != "nt" or attempt == 19:
                raise
            time.sleep(0.05)
    raise AssertionError("unreachable")  # pragma: no cover


def read_object(path: Path) -> dict[str, object]:
    """The stored JSON object. Missing -> {}. Corrupt or non-object -> raises ValueError."""
    try:
        text = _read_text(path)
    except FileNotFoundError:
        return {}
    if not text.strip():
        return {}  # the empty file v1.1.1 left behind: nothing to lose
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("secrets file is not a JSON object")
    return data


def set_value(path: Path, name: str, value: object) -> None:
    """Merge one key into the store: lock, read, update, atomic replace.

    Refuses to overwrite a file it cannot parse (same stance as the vendor's
    "Could not read secrets file. Aborting."): a corrupt store is left for the
    owner to look at, not silently reset to one key.
    """
    with locked(path):
        try:
            data = read_object(path)
        except (ValueError, OSError) as exc:  # JSONDecodeError is a ValueError
            raise RuntimeError("Could not read secrets file. Aborting.") from exc
        data[name] = value
        atomic_write_json(path, data)

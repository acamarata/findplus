"""An exclusive file lock that says "a Find+ daemon owns this state directory".

Purpose    : The HTTP probe in `cmd_serve._check_exclusive` misses a daemon that is
             still starting, wedged, or bound to another port. A held lock does not:
             `serve` takes it for as long as it runs, and `restore` / `rebuild-derived`
             refuse while it is held.
Inputs     : The state directory.
Outputs    : `acquire` returns an open file (keep it open, close it to release) or
             None when another process holds the lock; `is_held` is the read-only test.
Constraints: `<state dir>/daemon.lock`, POSIX `flock`. The kernel drops the lock when
             the process dies, so a crash never leaves a stale lock. On Windows there
             is no lock here: both functions say "not held" and the HTTP probe stays
             the only guard.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO

try:  # pragma: no cover - platform split
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

LOCK_NAME = "daemon.lock"


def acquire(state_dir: Path) -> IO[str] | None:
    """Take the lock; None when someone else holds it. Keep the result referenced."""
    if fcntl is None:
        return open(os.devnull)
    state_dir.mkdir(parents=True, exist_ok=True)
    fh = open(state_dir / LOCK_NAME, "a+")  # noqa: SIM115 - held for the process lifetime
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def is_held(state_dir: Path) -> bool:
    """True when another process holds the lock (the lock is not taken by asking)."""
    if fcntl is None or not (state_dir / LOCK_NAME).exists():
        return False
    fh = acquire(state_dir)
    if fh is None:
        return True
    fh.close()
    return False

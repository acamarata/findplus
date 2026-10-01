"""Shared cancel helpers for the two Chrome-window job modules.

Purpose    : browser.py (own-window sign-in) and unlock.py (own-window unlock) keep
             identical job tables (`_lock`, `_jobs`, `_active_job_id`). Disconnect
             must cancel whichever job is running, and a job that finishes after a
             cancel must store nothing; both modules need the same two checks, kept
             here so neither file grows past the size cap.
Inputs     : a job table (`_lock`, `_jobs`) or a job module (adds `_active_job_id`).
Outputs    : bool answers; no state of its own.
Constraints: A swept job is NOT treated as cancelled: only an explicit cancel is a
             reason to drop a key or a token the user already produced.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from types import ModuleType
from typing import Any

__all__ = ["cancel_active", "discard_late_secrets", "explicitly_cancelled"]


def explicitly_cancelled(lock: Any, jobs: dict[str, Any], job_id: str) -> bool:
    """True when cancel was called on `job_id` (the job record still exists)."""
    with lock:
        job = jobs.get(job_id)
        return job is not None and bool(job.get("cancelled"))


def cancel_active(module: ModuleType, cancel: Callable[[str], bool]) -> bool:
    """Cancel the module's running job with its own cancel function. False when none."""
    with module._lock:
        job_id = module._active_job_id
    return cancel(job_id) if job_id else False


def discard_late_secrets(settings: Any) -> None:
    """Delete the secrets file a cancelled sign-in wrote as it finished."""
    with contextlib.suppress(OSError):
        settings.secrets_file.unlink()

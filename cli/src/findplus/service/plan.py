"""Service plan: constants, the ServicePlan dataclass, and platform detection.

Purpose    : The data shape every platform builder returns, plus the shared
             private helpers (_python, _uid) and detect_manager(), which
             every other module in this package imports.
Constraints: No imports from sibling service/ modules — this is the leaf of
             the package's dependency graph.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path

LAUNCHD_LABEL = "com.acamarata.findplus"
WATCHDOG_LABEL = "com.acamarata.findplus.watchdog"
SYSTEMD_UNIT = "findplus.service"
WATCHDOG_TIMER = "findplus-watchdog.timer"
WATCHDOG_SERVICE = "findplus-watchdog.service"

#: How often the watchdog checks that the API is answering.
WATCHDOG_INTERVAL_SECONDS = 300


@dataclass(frozen=True, slots=True)
class ServicePlan:
    """What `install()` would do, rendered for review before it happens."""

    platform: str
    manager: str
    unit_path: Path
    unit_text: str
    load_command: list[str]
    unload_command: list[str]


def _python() -> str:
    """The interpreter running this code (the project venv when installed there)."""
    return sys.executable


def _uid() -> int:
    """POSIX process UID, used to build the `gui/<uid>` launchd domain target.

    Windows has no such concept and the schtasks builder never calls this —
    but the launchd/systemd plan builders are also exercised on Windows CI as
    pure string-generation regression tests (detect_manager monkeypatched to
    "launchd"/"systemd" regardless of host OS; see test_service_plans.py and
    test_start_at_login.py), so fall back to 0 rather than raise there. The
    real value is still used whenever it exists.
    """
    import os

    return os.getuid() if hasattr(os, "getuid") else 0


def detect_manager() -> str:
    system = platform.system()
    if system == "Darwin":
        return "launchd"
    if system == "Linux":
        return "systemd"
    if system == "Windows":
        return "schtasks"
    return "unsupported"

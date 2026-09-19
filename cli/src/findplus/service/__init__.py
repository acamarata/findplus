"""Autostart integration.

Purpose : Install/remove a user-level background service for the poller + API.
Constraints:
    - USER-level only. Nothing is written to /Library or /etc; no sudo is used.
    - `plan(...)` builds the unit text and `install(...)` refuses to act unless the
      caller passes `confirmed=True`, so the CLI can always show the exact file
      and the exact path before anything touches the system.

Full backward-compatible re-export: `from findplus import service` and
`service.plan()`/`service.LAUNCHD_LABEL` etc. keep resolving exactly as they
did against the pre-split service.py.
"""

from __future__ import annotations

from .plan import (
    LAUNCHD_LABEL,
    SYSTEMD_UNIT,
    WATCHDOG_INTERVAL_SECONDS,
    WATCHDOG_LABEL,
    WATCHDOG_SERVICE,
    WATCHDOG_TIMER,
    ServicePlan,
    detect_manager,
)
from .runtime import install, is_installed, is_running, plan, restart_service, uninstall
from .watchdog import install_watchdog, uninstall_watchdog, watchdog_installed, watchdog_plan

__all__ = [
    "LAUNCHD_LABEL",
    "SYSTEMD_UNIT",
    "WATCHDOG_INTERVAL_SECONDS",
    "WATCHDOG_LABEL",
    "WATCHDOG_SERVICE",
    "WATCHDOG_TIMER",
    "ServicePlan",
    "detect_manager",
    "install",
    "install_watchdog",
    "is_installed",
    "is_running",
    "plan",
    "restart_service",
    "uninstall",
    "uninstall_watchdog",
    "watchdog_installed",
    "watchdog_plan",
]

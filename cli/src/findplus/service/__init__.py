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

`ServiceStatus` plus the `stop`/`start`/`restart`/`status` facade functions
(added by P1-E7-W3-S1-T1) live directly in this module (not runtime.py) since
they are new surface, not a move of existing code; each dispatches on
`detect_manager()` at call time, exactly like every other facade function.
"""

from __future__ import annotations

from dataclasses import dataclass

from findplus.config import Settings, get_settings

from . import launchd, schtasks, systemd
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
from .runtime import (
    daemon_alive,
    install,
    is_installed,
    is_running,
    plan,
    read_daemon_file,
    restart_service,
    uninstall,
    write_daemon_file,
)
from .watchdog import (
    check_once,
    install_watchdog,
    restart_if_wedged,
    uninstall_watchdog,
    watchdog_installed,
    watchdog_plan,
)

__all__ = [
    "LAUNCHD_LABEL",
    "SYSTEMD_UNIT",
    "WATCHDOG_INTERVAL_SECONDS",
    "WATCHDOG_LABEL",
    "WATCHDOG_SERVICE",
    "WATCHDOG_TIMER",
    "ServicePlan",
    "ServiceStatus",
    "check_once",
    "daemon_alive",
    "detect_manager",
    "install",
    "install_watchdog",
    "is_installed",
    "is_running",
    "plan",
    "read_daemon_file",
    "restart",
    "restart_if_wedged",
    "restart_service",
    "start",
    "status",
    "stop",
    "uninstall",
    "uninstall_watchdog",
    "watchdog_installed",
    "watchdog_plan",
    "write_daemon_file",
]


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    """A snapshot of the service and watchdog jobs, plus the running daemon
    (from daemon.json) if one answered."""

    installed: bool
    loaded: bool
    running: bool
    watchdog_installed: bool
    watchdog_loaded: bool
    pid: int | None
    port: int | None
    version: str | None


def stop(settings: Settings | None = None) -> None:
    """Unload both jobs. Unit files (and, for schtasks, the task XML) are kept."""
    settings = settings or get_settings()
    manager = detect_manager()
    if manager == "launchd":
        launchd.bootout(plan(settings))
        launchd.bootout(watchdog_plan(settings))
    elif manager == "systemd":
        systemd.stop(SYSTEMD_UNIT)
        systemd.disable(SYSTEMD_UNIT)
        systemd.stop(WATCHDOG_TIMER)
        systemd.disable(WATCHDOG_TIMER)
    elif manager == "schtasks":
        schtasks.end(schtasks.TASK_NAME)
        schtasks.end(schtasks.WATCHDOG_TASK_NAME)
    else:
        raise RuntimeError("Windows service management lands in ticket P1-E7-W3-S1-T2")


def start(settings: Settings | None = None) -> None:
    """Bootstrap/enable both jobs — only when their unit files already exist."""
    settings = settings or get_settings()
    manager = detect_manager()
    if manager == "launchd":
        p = plan(settings)
        if not p.unit_path.exists():
            raise RuntimeError("Service not installed; run `findplus start --yes`.")
        launchd.bootstrap(p)
        w = watchdog_plan(settings)
        if w.unit_path.exists():
            launchd.bootstrap(w)
    elif manager == "systemd":
        p = plan(settings)
        if not p.unit_path.exists():
            raise RuntimeError("Service not installed; run `findplus start --yes`.")
        systemd.enable_now(SYSTEMD_UNIT)
        w = watchdog_plan(settings)
        if w.unit_path.exists():
            systemd.enable_now(WATCHDOG_TIMER)
    elif manager == "schtasks":
        schtasks.run(schtasks.TASK_NAME)
        if not schtasks.is_registered(schtasks.WATCHDOG_TASK_NAME):
            schtasks.create(watchdog_plan(settings))
    else:
        raise RuntimeError("Windows service management lands in ticket P1-E7-W3-S1-T2")


def restart(settings: Settings | None = None) -> None:
    manager = detect_manager()
    if manager in {"launchd", "systemd"}:
        restart_service()
    elif manager == "schtasks":
        schtasks.end(schtasks.TASK_NAME)
        schtasks.run(schtasks.TASK_NAME)
    else:
        raise RuntimeError("Windows service management lands in ticket P1-E7-W3-S1-T2")


def status(settings: Settings | None = None) -> ServiceStatus:
    settings = settings or get_settings()
    manager = detect_manager()
    d = read_daemon_file(settings)
    pid = d.get("pid") if d else None
    port = d.get("port") if d else None
    version = d.get("version") if d else None

    if manager == "launchd":
        installed = plan(settings).unit_path.exists()
        loaded = launchd.is_loaded(LAUNCHD_LABEL)
        running = is_running(settings)
        wd_installed = watchdog_installed(settings)
        wd_loaded = launchd.is_loaded(WATCHDOG_LABEL)
    elif manager == "systemd":
        installed = plan(settings).unit_path.exists()
        loaded = systemd.is_active(SYSTEMD_UNIT)
        running = is_running(settings)
        wd_installed = watchdog_installed(settings)
        wd_loaded = systemd.is_active(WATCHDOG_TIMER)
    elif manager == "schtasks":
        installed = settings.task_xml_path.exists()
        loaded = schtasks.is_registered(schtasks.TASK_NAME)
        running = loaded
        wd_installed = schtasks.is_registered(schtasks.WATCHDOG_TASK_NAME)
        wd_loaded = wd_installed
    else:
        raise RuntimeError("Windows service management lands in ticket P1-E7-W3-S1-T2")

    return ServiceStatus(
        installed=installed,
        loaded=loaded,
        running=running,
        watchdog_installed=wd_installed,
        watchdog_loaded=wd_loaded,
        pid=pid,
        port=port,
        version=version,
    )

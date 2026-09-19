"""Watchdog public API: a second, independent job that restarts the poller
if it stops answering (not to be confused with the CLI's `findplus watchdog`
health-check command, which calls the local API directly).

Purpose    : The `findplus install-watchdog` surface, dispatched by platform.
Constraints: `KeepAlive` already restarts the service when the process
             *dies*. This covers the other failure mode: alive but wedged.
             No schtasks (Windows) watchdog exists yet — matches the
             pre-split service.py exactly (RuntimeError on that platform).
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from findplus.config import Settings, get_settings

from . import launchd, systemd
from .plan import WATCHDOG_SERVICE, ServicePlan, detect_manager


def watchdog_plan(settings: Settings | None = None) -> ServicePlan:
    settings = settings or get_settings()
    settings.ensure_dirs()
    manager = detect_manager()

    if manager == "launchd":
        return launchd.watchdog_plan_launchd(settings)
    if manager == "systemd":
        return systemd.watchdog_plan_systemd(settings)
    raise RuntimeError(f"The watchdog is not supported on {platform.system()}.")


def install_watchdog(settings: Settings | None = None, *, confirmed: bool = False) -> ServicePlan:
    p = watchdog_plan(settings)
    if not confirmed:
        raise PermissionError("Refusing to install the watchdog without explicit confirmation.")
    p.unit_path.parent.mkdir(parents=True, exist_ok=True)
    p.unit_path.write_text(p.unit_text, encoding="utf-8")
    if p.manager.startswith("systemd"):
        settings = settings or get_settings()
        service_path = Path.home() / ".config" / "systemd" / "user" / WATCHDOG_SERVICE
        service_path.write_text(systemd.watchdog_service_unit_text(settings), encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(p.load_command, check=False)
    return p


def uninstall_watchdog(settings: Settings | None = None) -> ServicePlan:
    p = watchdog_plan(settings)
    subprocess.run(p.unload_command, check=False)
    if p.unit_path.exists():
        p.unit_path.unlink()
    return p


def watchdog_installed(settings: Settings | None = None) -> bool:
    try:
        return watchdog_plan(settings).unit_path.exists()
    except RuntimeError:
        return False

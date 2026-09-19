"""Main service public API: plan/install/uninstall/status, dispatched by
platform.

Purpose    : The `findplus start|stop|status` surface. Each function calls
             detect_manager() at CALL time (not import time) so tests can
             monkeypatch it per-test without reloading this module.
Constraints: USER-level only. Nothing is written to /Library or /etc; no
             sudo is used. install() refuses to act unless confirmed=True.
"""

from __future__ import annotations

import platform
import shutil
import subprocess

from findplus.config import Settings, get_settings

from . import launchd, schtasks, systemd
from .plan import LAUNCHD_LABEL, SYSTEMD_UNIT, ServicePlan, _uid, detect_manager


def plan(settings: Settings | None = None) -> ServicePlan:
    """Describe the service that would be installed. Performs no changes."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    manager = detect_manager()

    if manager == "launchd":
        return launchd.plan_launchd(settings)
    if manager == "systemd":
        return systemd.plan_systemd(settings)
    if manager == "schtasks":
        return schtasks.plan_schtasks(settings)
    raise RuntimeError(f"Autostart is not supported on {platform.system()}.")


def install(settings: Settings | None = None, *, confirmed: bool = False) -> ServicePlan:
    """Write and load the service. Refuses without explicit confirmation."""
    p = plan(settings)
    if not confirmed:
        raise PermissionError(
            "Refusing to install a background service without explicit confirmation."
        )
    p.unit_path.parent.mkdir(parents=True, exist_ok=True)
    p.unit_path.write_text(p.unit_text, encoding="utf-8")

    if p.manager.startswith("systemd"):
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(p.load_command, check=False)
    return p


def uninstall(settings: Settings | None = None) -> ServicePlan:
    """Unload and remove the service unit."""
    p = plan(settings)
    subprocess.run(p.unload_command, check=False)
    if p.unit_path.exists() and p.manager != "Task Scheduler (current user, at logon)":
        p.unit_path.unlink()
    return p


def is_installed(settings: Settings | None = None) -> bool:
    try:
        return plan(settings).unit_path.exists()
    except RuntimeError:
        return False


def is_running(settings: Settings | None = None) -> bool:
    """Ask the platform service manager whether our job is loaded."""
    manager = detect_manager()
    if manager == "launchd" and shutil.which("launchctl"):
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=False)
        return LAUNCHD_LABEL in out.stdout
    if manager == "systemd" and shutil.which("systemctl"):
        out = subprocess.run(
            ["systemctl", "--user", "is-active", SYSTEMD_UNIT],
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.strip() == "active"
    return False


def restart_service() -> bool:
    """Force the main service to restart. Returns True if the command was issued."""
    manager = detect_manager()
    if manager == "launchd" and shutil.which("launchctl"):
        subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{_uid()}/{LAUNCHD_LABEL}"], check=False
        )
        return True
    if manager == "systemd" and shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "restart", SYSTEMD_UNIT], check=False)
        return True
    return False

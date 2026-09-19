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

import json
import platform
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from findplus.config import Settings, get_settings
from findplus.logging_setup import get_logger

from . import launchd, schtasks, systemd
from .plan import WATCHDOG_SERVICE, ServicePlan, detect_manager
from .runtime import read_daemon_file

log = get_logger(__name__)


def watchdog_plan(settings: Settings | None = None, *, program: str | None = None) -> ServicePlan:
    settings = settings or get_settings()
    settings.ensure_dirs()
    manager = detect_manager()

    if manager == "launchd":
        return launchd.watchdog_plan_launchd(settings, program=program)
    if manager == "systemd":
        return systemd.watchdog_plan_systemd(settings, program=program)
    if manager == "schtasks":
        return schtasks.watchdog_plan_schtasks(settings, program=program)
    raise RuntimeError(f"The watchdog is not supported on {platform.system()}.")


def install_watchdog(
    settings: Settings | None = None, *, confirmed: bool = False, program: str | None = None
) -> ServicePlan:
    p = watchdog_plan(settings, program=program)
    if not confirmed:
        raise PermissionError("Refusing to install the watchdog without explicit confirmation.")
    if p.manager.startswith("Task Scheduler"):
        schtasks.create(p)
        return p
    p.unit_path.parent.mkdir(parents=True, exist_ok=True)
    p.unit_path.write_text(p.unit_text, encoding="utf-8")
    if p.manager.startswith("systemd"):
        settings = settings or get_settings()
        service_path = Path.home() / ".config" / "systemd" / "user" / WATCHDOG_SERVICE
        service_path.write_text(
            systemd.watchdog_service_unit_text(settings, program=program), encoding="utf-8"
        )
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(p.load_command, check=False)
    return p


def uninstall_watchdog(settings: Settings | None = None) -> ServicePlan:
    p = watchdog_plan(settings)
    if p.manager.startswith("Task Scheduler"):
        schtasks.delete(schtasks.WATCHDOG_TASK_NAME)
        return p
    subprocess.run(p.unload_command, check=False)
    if p.unit_path.exists():
        p.unit_path.unlink()
    return p


def watchdog_installed(settings: Settings | None = None) -> bool:
    try:
        p = watchdog_plan(settings)
    except RuntimeError:
        return False
    if p.manager.startswith("Task Scheduler"):
        return schtasks.is_registered(schtasks.WATCHDOG_TASK_NAME)
    return p.unit_path.exists()


def check_once(settings: Settings) -> tuple[bool, str]:
    """Probe the daemon's health endpoint. The port in daemon.json is
    authoritative while the daemon runs (it may differ from settings.port —
    the user changed it after install, or the desktop app started the daemon
    on another port). A mismatch is logged; a 401 (locked, still running) is
    healthy; only an unreachable or foreign-app daemon is unhealthy."""
    try:
        d = read_daemon_file(settings)
    except (OSError, ValueError, KeyError):
        d = None

    probe_port = settings.port
    if d is not None:
        try:
            probe_port = int(d["port"])
        except (KeyError, TypeError, ValueError):
            probe_port = settings.port

    if d is not None and probe_port != settings.port:
        log.warning("watchdog_port_mismatch", settings_port=settings.port, daemon_port=probe_port)

    url = f"http://{settings.host}:{probe_port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            if response.status == 200:
                app = json.loads(response.read()).get("app")
                if app == "findplus":
                    return (True, "ok")
                return (False, "port used by a different service")
            return (False, f"HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return (True, "locked but responding")
        return (False, f"HTTP {exc.code}")
    except Exception as exc:
        return (False, str(exc))


def restart_if_wedged(settings: Settings) -> str:
    """Restart the service only when `check_once` reports it unhealthy."""
    healthy, detail = check_once(settings)
    if healthy:
        log.info("watchdog_ok", note=detail)
        return detail

    log.error("watchdog_restarting", problem=detail)
    from findplus import service  # lazy: service/__init__ imports this module

    if service.restart_service():
        return f"restarted ({detail})"
    return f"not answering ({detail}); no service installed"

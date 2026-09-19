"""Autostart integration.

Purpose : Install/remove a user-level background service for the poller + API.
Constraints:
    - USER-level only. Nothing is written to /Library or /etc; no sudo is used.
    - `render_*` builds the unit text and `install(...)` refuses to act unless the
      caller passes `confirmed=True`, so the CLI can always show the exact file
      and the exact path before anything touches the system.
"""

from __future__ import annotations

import platform
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from findplus.config import PROJECT_ROOT, Settings, get_settings

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


def detect_manager() -> str:
    system = platform.system()
    if system == "Darwin":
        return "launchd"
    if system == "Linux":
        return "systemd"
    if system == "Windows":
        return "schtasks"
    return "unsupported"


def plan(settings: Settings | None = None) -> ServicePlan:
    """Describe the service that would be installed. Performs no changes."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    manager = detect_manager()

    if manager == "launchd":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        payload = {
            "Label": LAUNCHD_LABEL,
            "ProgramArguments": [_python(), "-m", "findplus.cli", "serve", "--foreground"],
            "WorkingDirectory": str(PROJECT_ROOT),
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "StandardOutPath": str(settings.log_dir / "service.out.log"),
            "StandardErrorPath": str(settings.log_dir / "service.err.log"),
            "EnvironmentVariables": {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
                "FINDPLUS_STATE_DIR": str(settings.state_dir),
            },
            "ProcessType": "Background",
            # Wake from sleep should not stampede; the poller applies its own interval.
            "ThrottleInterval": 30,
        }
        text = plistlib.dumps(payload).decode("utf-8")
        uid = _uid()
        return ServicePlan(
            platform="macOS",
            manager="launchd (user LaunchAgent)",
            unit_path=path,
            unit_text=text,
            load_command=["launchctl", "bootstrap", f"gui/{uid}", str(path)],
            unload_command=["launchctl", "bootout", f"gui/{uid}/{LAUNCHD_LABEL}"],
        )

    if manager == "systemd":
        path = Path.home() / ".config" / "systemd" / "user" / SYSTEMD_UNIT
        text = f"""[Unit]
Description=findplus — local Find Hub location history
After=network-online.target

[Service]
Type=simple
WorkingDirectory={PROJECT_ROOT}
Environment=FINDPLUS_STATE_DIR={settings.state_dir}
ExecStart={_python()} -m findplus.cli serve --foreground
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
"""
        return ServicePlan(
            platform="Linux",
            manager="systemd (user service)",
            unit_path=path,
            unit_text=text,
            load_command=["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT],
            unload_command=["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT],
        )

    if manager == "schtasks":
        path = PROJECT_ROOT / "deploy" / "findplus-task.xml"
        command = f'"{_python()}" -m findplus.cli serve --foreground'
        return ServicePlan(
            platform="Windows",
            manager="Task Scheduler (current user, at logon)",
            unit_path=path,
            unit_text=command,
            load_command=[
                "schtasks",
                "/Create",
                "/TN",
                "FindPlus",
                "/SC",
                "ONLOGON",
                "/TR",
                command,
                "/F",
            ],
            unload_command=["schtasks", "/Delete", "/TN", "FindPlus", "/F"],
        )

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


def _uid() -> int:
    import os

    return os.getuid()


# ---------------------------------------------------------------- watchdog
def watchdog_plan(settings: Settings | None = None) -> ServicePlan:
    """A second, independent job that restarts the poller if it stops answering.

    `KeepAlive` already restarts the service when the process *dies*. This covers
    the other failure mode: the process is alive but the API has wedged, which
    KeepAlive cannot see.
    """
    settings = settings or get_settings()
    settings.ensure_dirs()
    manager = detect_manager()

    if manager == "launchd":
        path = Path.home() / "Library" / "LaunchAgents" / f"{WATCHDOG_LABEL}.plist"
        payload = {
            "Label": WATCHDOG_LABEL,
            "ProgramArguments": [_python(), "-m", "findplus.cli", "watchdog"],
            "WorkingDirectory": str(PROJECT_ROOT),
            "RunAtLoad": True,
            "StartInterval": WATCHDOG_INTERVAL_SECONDS,
            "StandardOutPath": str(settings.log_dir / "watchdog.out.log"),
            "StandardErrorPath": str(settings.log_dir / "watchdog.err.log"),
            "EnvironmentVariables": {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
                "FINDPLUS_STATE_DIR": str(settings.state_dir),
            },
            "ProcessType": "Background",
        }
        uid = _uid()
        return ServicePlan(
            platform="macOS",
            manager="launchd (user LaunchAgent, watchdog)",
            unit_path=path,
            unit_text=plistlib.dumps(payload).decode("utf-8"),
            load_command=["launchctl", "bootstrap", f"gui/{uid}", str(path)],
            unload_command=["launchctl", "bootout", f"gui/{uid}/{WATCHDOG_LABEL}"],
        )

    if manager == "systemd":
        path = Path.home() / ".config" / "systemd" / "user" / WATCHDOG_TIMER
        text = f"""[Unit]
Description=findplus watchdog

[Timer]
OnBootSec=2min
OnUnitActiveSec={WATCHDOG_INTERVAL_SECONDS}s

[Install]
WantedBy=timers.target
"""
        return ServicePlan(
            platform="Linux",
            manager="systemd (user timer, watchdog)",
            unit_path=path,
            unit_text=text,
            load_command=["systemctl", "--user", "enable", "--now", WATCHDOG_TIMER],
            unload_command=["systemctl", "--user", "disable", "--now", WATCHDOG_TIMER],
        )

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
        service_path.write_text(
            f"""[Unit]
Description=findplus watchdog check

[Service]
Type=oneshot
Environment=FINDPLUS_STATE_DIR={settings.state_dir}
ExecStart={_python()} -m findplus.cli watchdog
""",
            encoding="utf-8",
        )
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

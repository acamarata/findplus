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

from bike_tracker.config import PROJECT_ROOT, Settings, get_settings

LAUNCHD_LABEL = "com.acamarata.bike-tracker"
SYSTEMD_UNIT = "bike-tracker.service"


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
            "ProgramArguments": [_python(), "-m", "bike_tracker.cli", "serve", "--foreground"],
            "WorkingDirectory": str(PROJECT_ROOT),
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "StandardOutPath": str(settings.log_dir / "service.out.log"),
            "StandardErrorPath": str(settings.log_dir / "service.err.log"),
            "EnvironmentVariables": {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
                "BIKE_TRACKER_STATE_DIR": str(settings.state_dir),
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
Description=bike-tracker — local Find Hub location history
After=network-online.target

[Service]
Type=simple
WorkingDirectory={PROJECT_ROOT}
Environment=BIKE_TRACKER_STATE_DIR={settings.state_dir}
ExecStart={_python()} -m bike_tracker.cli serve --foreground
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
        path = PROJECT_ROOT / "deploy" / "bike-tracker-task.xml"
        command = f'"{_python()}" -m bike_tracker.cli serve --foreground'
        return ServicePlan(
            platform="Windows",
            manager="Task Scheduler (current user, at logon)",
            unit_path=path,
            unit_text=command,
            load_command=[
                "schtasks",
                "/Create",
                "/TN",
                "BikeTracker",
                "/SC",
                "ONLOGON",
                "/TR",
                command,
                "/F",
            ],
            unload_command=["schtasks", "/Delete", "/TN", "BikeTracker", "/F"],
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

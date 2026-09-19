"""systemd plan builders (Linux user services/timers) for the main service and
the watchdog.

Purpose    : Build the exact unit-file ServicePlan for each job, plus the
             watchdog's oneshot check-service unit text (written directly by
             watchdog.install_watchdog, not returned as a ServicePlan since
             it is a second file alongside the timer unit).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from findplus.config import PROJECT_ROOT, Settings

from .plan import SYSTEMD_UNIT, WATCHDOG_INTERVAL_SECONDS, WATCHDOG_TIMER, ServicePlan, _python


def plan_systemd(settings: Settings, *, program: str | None = None) -> ServicePlan:
    path = Path.home() / ".config" / "systemd" / "user" / SYSTEMD_UNIT
    base = [program] if program else [_python(), "-m", "findplus.cli"]
    exec_start = " ".join([*base, "serve", "--foreground"])
    text = f"""[Unit]
Description=findplus — local Find Hub location history
After=network-online.target

[Service]
Type=simple
WorkingDirectory={PROJECT_ROOT}
Environment=FINDPLUS_STATE_DIR={settings.state_dir}
ExecStart={exec_start}
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


def watchdog_plan_systemd(settings: Settings, *, program: str | None = None) -> ServicePlan:
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


def watchdog_service_unit_text(settings: Settings, *, program: str | None = None) -> str:
    """The oneshot `findplus-watchdog.service` content the timer above triggers."""
    base = [program] if program else [_python(), "-m", "findplus.cli"]
    exec_start = " ".join([*base, "watchdog"])
    return f"""[Unit]
Description=findplus watchdog check

[Service]
Type=oneshot
Environment=FINDPLUS_STATE_DIR={settings.state_dir}
ExecStart={exec_start}
"""


def enable_now(unit: str) -> None:
    """`systemctl --user enable --now <unit>`."""
    subprocess.run(["systemctl", "--user", "enable", "--now", unit], check=False)


def stop(unit: str) -> None:
    """`systemctl --user stop <unit>`. Keeps the unit enabled."""
    subprocess.run(["systemctl", "--user", "stop", unit], check=False)


def disable(unit: str) -> None:
    """`systemctl --user disable <unit>`."""
    subprocess.run(["systemctl", "--user", "disable", unit], check=False)


def is_active(unit: str) -> bool:
    out = subprocess.run(
        ["systemctl", "--user", "is-active", unit],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip() == "active"


def daemon_reload() -> None:
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)

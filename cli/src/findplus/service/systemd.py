"""systemd plan builders (Linux user services/timers) for the main service and
the watchdog.

Purpose    : Build the exact unit-file ServicePlan for each job, plus the
             watchdog's oneshot check-service unit text (written directly by
             watchdog.install_watchdog, not returned as a ServicePlan since
             it is a second file alongside the timer unit).
"""

from __future__ import annotations

from pathlib import Path

from findplus.config import PROJECT_ROOT, Settings

from .plan import SYSTEMD_UNIT, WATCHDOG_INTERVAL_SECONDS, WATCHDOG_TIMER, ServicePlan, _python


def plan_systemd(settings: Settings) -> ServicePlan:
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


def watchdog_plan_systemd(settings: Settings) -> ServicePlan:
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


def watchdog_service_unit_text(settings: Settings) -> str:
    """The oneshot `findplus-watchdog.service` content the timer above triggers."""
    return f"""[Unit]
Description=findplus watchdog check

[Service]
Type=oneshot
Environment=FINDPLUS_STATE_DIR={settings.state_dir}
ExecStart={_python()} -m findplus.cli watchdog
"""

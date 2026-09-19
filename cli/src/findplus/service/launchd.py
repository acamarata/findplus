"""launchd plan builders (macOS user LaunchAgents) for the main service and
the watchdog.

Purpose    : Build the exact plist ServicePlan for each job. No installation
             logic here — runtime.py/watchdog.py write and load what this
             returns.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from findplus.config import PROJECT_ROOT, Settings

from ._proc import run as _run
from .plan import (
    LAUNCHD_LABEL,
    WATCHDOG_INTERVAL_SECONDS,
    WATCHDOG_LABEL,
    ServicePlan,
    _python,
    _uid,
)


def plan_launchd(settings: Settings, *, program: str | None = None) -> ServicePlan:
    path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
    base = [program] if program else [_python(), "-m", "findplus.cli"]
    payload = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [*base, "serve", "--foreground"],
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


def watchdog_plan_launchd(settings: Settings, *, program: str | None = None) -> ServicePlan:
    """A second, independent job that restarts the poller if it stops answering.

    `KeepAlive` already restarts the service when the process *dies*. This covers
    the other failure mode: the process is alive but the API has wedged, which
    KeepAlive cannot see.
    """
    path = Path.home() / "Library" / "LaunchAgents" / f"{WATCHDOG_LABEL}.plist"
    base = [program] if program else [_python(), "-m", "findplus.cli"]
    payload = {
        "Label": WATCHDOG_LABEL,
        "ProgramArguments": [*base, "watchdog"],
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


def bootstrap(plan: ServicePlan) -> None:
    """Load a launchd job (`launchctl bootstrap gui/<uid> <plist>`)."""
    _run(plan.load_command)


def bootout(plan: ServicePlan) -> None:
    """Unload a launchd job. Keeps the plist file on disk."""
    _run(plan.unload_command)


def kickstart(label: str) -> None:
    """Force-restart a loaded launchd job."""
    _run(["launchctl", "kickstart", "-k", f"gui/{_uid()}/{label}"])


def is_loaded(label: str) -> bool:
    """Whether `label` is currently loaded in the user's launchd domain."""
    out = _run(["launchctl", "print", f"gui/{_uid()}/{label}"], capture=True)
    return out.returncode == 0

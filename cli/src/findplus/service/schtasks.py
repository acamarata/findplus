"""Windows Task Scheduler plan builder for the main service.

Purpose    : Build the ServicePlan for `schtasks /Create`. There is no
             watchdog builder here yet — the pre-split service.py never
             implemented a Windows watchdog path, and watchdog_plan() raises
             RuntimeError on Windows exactly as it did before this split.
"""

from __future__ import annotations

from findplus.config import PROJECT_ROOT, Settings

from .plan import ServicePlan, _python


def plan_schtasks(settings: Settings) -> ServicePlan:
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

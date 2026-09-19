"""Windows Task Scheduler plan builders and actions for the main service and
the watchdog.

Purpose    : Build the ServicePlan for `schtasks /Create` (main service, one
             XML file) and for the watchdog (switches only, no XML file — the
             data model pins exactly one state-dir XML: FindPlus-task.xml).
             Also wraps every schtasks.exe subprocess call.
Constraints: Windows cannot use launchd or systemd (D13). Every function here
             is unit-tested on macOS/Linux CI: `_task_xml` is a pure string
             helper, and every schtasks.exe call is mocked in tests. No
             unit_path lives outside the user's state dir.
"""

from __future__ import annotations

import subprocess

from findplus.config import Settings

from .plan import ServicePlan, _python

TASK_NAME = "FindPlus"
WATCHDOG_TASK_NAME = "FindPlusWatchdog"


def _task_xml(program: str, args: list[str]) -> str:
    """Pure-string Task Scheduler XML for a logon-triggered task.

    `program` is written verbatim into <Command> — XML needs no shell quoting,
    so a path with spaces (e.g. inside "Program Files") is safe as-is.
    """
    arguments = " ".join(args)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Find+ location daemon</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Hidden>false</Hidden>
    <StartWhenAvailable>true</StartWhenAvailable>
  </Settings>
  <Actions>
    <Exec>
      <Command>{program}</Command>
      <Arguments>{arguments}</Arguments>
    </Exec>
  </Actions>
  <Principals>
    <Principal>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
</Task>
"""


def plan_schtasks(settings: Settings, *, program: str | None = None) -> ServicePlan:
    base = [program] if program else [_python(), "-m", "findplus.cli"]
    argv = [*base, "serve", "--foreground"]
    return ServicePlan(
        platform="Windows",
        manager="Task Scheduler (current user, at logon)",
        unit_path=settings.task_xml_path,
        unit_text=_task_xml(base[0], argv[1:]),
        load_command=[
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/XML",
            str(settings.task_xml_path),
            "/F",
        ],
        unload_command=["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
    )


def watchdog_plan_schtasks(settings: Settings, *, program: str | None = None) -> ServicePlan:
    """Registered by switches only — no second XML file (data-model pins exactly
    one, FindPlus-task.xml). `unit_text` is empty and `install()` must not write
    it; `unit_path` is only carried for symmetry with the ServicePlan shape."""
    parts = ([program] if program else [_python(), "-m", "findplus.cli"]) + ["watchdog"]
    command = " ".join([f'"{parts[0]}"', *parts[1:]])
    return ServicePlan(
        platform="Windows",
        manager="Task Scheduler (current user, watchdog)",
        unit_path=settings.task_xml_path,
        unit_text="",
        load_command=[
            "schtasks",
            "/Create",
            "/TN",
            WATCHDOG_TASK_NAME,
            "/SC",
            "MINUTE",
            "/MO",
            "5",
            "/TR",
            command,
            "/F",
        ],
        unload_command=["schtasks", "/Delete", "/TN", WATCHDOG_TASK_NAME, "/F"],
    )


def create(plan: ServicePlan) -> None:
    subprocess.run(plan.load_command, check=False)


def delete(name: str) -> None:
    subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], check=False)


def run(name: str) -> None:
    subprocess.run(["schtasks", "/Run", "/TN", name], check=False)


def end(name: str) -> None:
    subprocess.run(["schtasks", "/End", "/TN", name], check=False)


def is_registered(name: str) -> bool:
    out = subprocess.run(["schtasks", "/Query", "/TN", name], capture_output=True, check=False)
    return out.returncode == 0

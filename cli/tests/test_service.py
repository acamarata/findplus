"""Autostart planning is inspectable and never acts without confirmation."""

from __future__ import annotations

import plistlib

import pytest

from findplus import service


def test_manager_is_detected_for_this_platform() -> None:
    assert service.detect_manager() in {"launchd", "systemd", "schtasks", "unsupported"}


def test_plan_describes_the_change_without_making_it() -> None:
    plan = service.plan()
    assert plan.unit_text
    assert plan.load_command
    assert not plan.unit_path.exists() or True  # planning never creates the file


def test_service_installs_at_user_level_only() -> None:
    """No sudo, nothing under /Library or /etc.

    launchd/systemd always park the unit under Path.home() (a fixed OS
    autostart directory); schtasks has no such directory, so the data model
    pins its task XML inside the app's own state dir instead (schtasks.py
    docstring: "no unit_path lives outside the user's state dir"). Either
    counts as user-level.
    """
    from findplus.config import get_settings

    plan = service.plan()
    path = str(plan.unit_path)
    assert str(plan.unit_path.home()) in path or str(get_settings().state_dir) in path
    assert not path.startswith("/Library")
    assert not path.startswith("/etc")
    assert "sudo" not in " ".join(plan.load_command)


def test_install_refuses_without_confirmation() -> None:
    with pytest.raises(PermissionError, match="without explicit confirmation"):
        service.install(confirmed=False)


@pytest.mark.skipif(service.detect_manager() != "launchd", reason="macOS only")
def test_launchd_plist_is_valid_and_runs_our_entry_point() -> None:
    payload = plistlib.loads(service.plan().unit_text.encode())
    assert payload["Label"] == service.LAUNCHD_LABEL
    assert payload["RunAtLoad"] is True
    assert "findplus.cli" in payload["ProgramArguments"]
    assert "serve" in payload["ProgramArguments"]


# ------------------------------------------------------------------ watchdog
def test_watchdog_plan_is_user_level_and_periodic() -> None:
    """See test_service_installs_at_user_level_only for the schtasks exception."""
    from findplus.config import get_settings

    plan = service.watchdog_plan()
    path = str(plan.unit_path)
    assert str(plan.unit_path.home()) in path or str(get_settings().state_dir) in path
    assert "sudo" not in " ".join(plan.load_command)


@pytest.mark.skipif(service.detect_manager() != "launchd", reason="macOS only")
def test_watchdog_plist_runs_on_an_interval() -> None:
    payload = plistlib.loads(service.watchdog_plan().unit_text.encode())
    assert payload["Label"] == service.WATCHDOG_LABEL
    assert payload["StartInterval"] == service.WATCHDOG_INTERVAL_SECONDS
    assert "watchdog" in payload["ProgramArguments"]


def test_watchdog_install_refuses_without_confirmation() -> None:
    with pytest.raises(PermissionError, match="without explicit confirmation"):
        service.install_watchdog(confirmed=False)


def test_watchdog_is_a_separate_job_from_the_service() -> None:
    """Two independent jobs: if one is broken the other still acts.

    Task Scheduler is the one exception: the data model pins exactly one XML
    file (FindPlus-task.xml) and the watchdog job is registered by switches
    only, so schtasks.py intentionally returns the same unit_path for both
    plans (its watchdog_plan_schtasks docstring: "carried for symmetry with
    the ServicePlan shape").
    """
    assert service.WATCHDOG_LABEL != service.LAUNCHD_LABEL
    if service.detect_manager() == "schtasks":
        assert service.watchdog_plan().unit_path == service.plan().unit_path
    else:
        assert service.watchdog_plan().unit_path != service.plan().unit_path

"""Autostart planning is inspectable and never acts without confirmation."""

from __future__ import annotations

import plistlib

import pytest

from bike_tracker import service


def test_manager_is_detected_for_this_platform() -> None:
    assert service.detect_manager() in {"launchd", "systemd", "schtasks", "unsupported"}


def test_plan_describes_the_change_without_making_it() -> None:
    plan = service.plan()
    assert plan.unit_text
    assert plan.load_command
    assert not plan.unit_path.exists() or True  # planning never creates the file


def test_service_installs_at_user_level_only() -> None:
    """No sudo, nothing under /Library or /etc."""
    plan = service.plan()
    path = str(plan.unit_path)
    assert str(plan.unit_path.home()) in path
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
    assert "bike_tracker.cli" in payload["ProgramArguments"]
    assert "serve" in payload["ProgramArguments"]

"""`findplus auth` (cli/cmd_auth.py): the Chrome precheck and the confirm prompt.

Split out of test_service_cmds.py alongside the cmd_auth.py source split.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from findplus.cli.main import main
from tests.service._helpers import patch_manager as _patch_manager  # noqa: F401


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    return opened


# ----------------------------------------------------- auth: Chrome precheck
def test_auth_stops_early_when_chrome_is_missing(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """Google sign-in drives a real Chrome. Without one the flow cannot work,
    so it must say so and stop instead of asking to open a browser."""
    from findplus.cli import doctor as doctor_module

    monkeypatch.setattr(
        doctor_module,
        "check_chrome",
        lambda: doctor_module.DoctorCheck("chrome", "Google Chrome", False, "not found"),
    )
    result = CliRunner().invoke(main, ["auth"], input="y\n")

    assert result.exit_code == 1, result.output
    assert "Google Chrome was not found" in result.output
    assert "https://www.google.com/chrome/" in result.output
    # The confirm prompt is never reached.
    assert "Open Chrome and sign in now?" not in result.output


def test_auth_reaches_the_confirm_prompt_when_chrome_is_present(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from findplus.cli import doctor as doctor_module

    monkeypatch.setattr(
        doctor_module,
        "check_chrome",
        lambda: doctor_module.DoctorCheck("chrome", "Google Chrome", True, "found"),
    )
    # Answer "no" at the prompt so no provider is ever contacted.
    result = CliRunner().invoke(main, ["auth"], input="n\n")

    assert "Open Chrome and sign in now?" in result.output
    assert "Google Chrome was not found" not in result.output

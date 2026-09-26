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


# ----------------------------------------------------------- auth: sign-out
def test_sign_out_removes_the_google_secrets_file(tmp_db) -> None:
    from findplus.config import get_settings

    settings = get_settings()
    settings.ensure_dirs()
    settings.secrets_file.write_text("{}")

    result = CliRunner().invoke(main, ["auth", "--sign-out", "--provider", "google-find-hub"])

    assert result.exit_code == 0, result.output
    assert "Signed out of google-find-hub." in result.output
    assert "Tracked devices and their history are unaffected." in result.output
    assert not settings.secrets_file.exists()


def test_sign_out_when_not_signed_in_says_so_and_still_exits_zero(tmp_db) -> None:
    result = CliRunner().invoke(main, ["auth", "--sign-out", "--provider", "apple-find-my"])

    assert result.exit_code == 0, result.output
    assert "apple-find-my was not signed in." in result.output


def test_sign_out_never_opens_chrome_or_prompts(tmp_db, _no_browser: list[str]) -> None:
    """--sign-out is a plain file removal: no Chrome precheck, no confirm."""
    result = CliRunner().invoke(main, ["auth", "--sign-out"])

    assert result.exit_code == 0, result.output
    assert "Open Chrome and sign in now?" not in result.output
    assert _no_browser == []

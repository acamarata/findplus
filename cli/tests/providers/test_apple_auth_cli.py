"""`findplus auth --provider ...` honesty guard.

E3 review carry-forward #19: the Google-specific preamble ("Google sign-in",
"Chrome will open", the pkill warning, the AAS/FCM/owner-key storage list) must
never appear for --provider apple-find-my, and the flag must reject an unknown
provider name via click.Choice. Uses CliRunner against the real `main` group;
never touches the network (findmy is not installed in this venv, so the Apple
branch takes its "not installed" exit before any I/O).
"""

from __future__ import annotations

from click.testing import CliRunner

from findplus.cli.main import main

_GOOGLE_ONLY_PHRASES = (
    "Google sign-in",
    "Chrome will open",
    "pkill -f chrome",
    "Android (AAS)",
)


def test_apple_provider_never_shows_google_wording(tmp_db) -> None:
    result = CliRunner().invoke(main, ["auth", "--provider", "apple-find-my"])
    for phrase in _GOOGLE_ONLY_PHRASES:
        assert phrase not in result.output, f"Google-only text leaked: {phrase!r}"
    assert "Apple Find My sign-in" in result.output or "Apple provider not installed" in (
        result.output
    )


def test_invalid_provider_rejected(tmp_db) -> None:
    result = CliRunner().invoke(main, ["auth", "--provider", "bogus-provider"])
    assert result.exit_code != 0
    assert "Invalid value" in result.output or "invalid choice" in result.output.lower()


def test_default_provider_still_shows_google_wording(tmp_db) -> None:
    """Regression guard: the fix must not remove the Google preamble either."""
    result = CliRunner().invoke(main, ["auth"], input="n\n")
    assert "Google sign-in" in result.output

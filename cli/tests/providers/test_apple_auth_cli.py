"""`findplus auth --provider ...` honesty guard.

E3 review carry-forward #19: the Google-specific preamble ("Google sign-in",
"Chrome will open", the pkill warning, the AAS/FCM/owner-key storage list) must
never appear for --provider apple-find-my, and the flag must reject an unknown
provider name via click.Choice. Uses CliRunner against the real `main` group;
Both states of the optional extra are exercised explicitly: is_available() and
sign_in_interactive() are stubbed, so these tests behave identically whether or
not `findmy` is installed and never construct a real AppleAccount or anisette
provider (PRI hard rule 3: tests never touch the network).
"""

from __future__ import annotations

from click.testing import CliRunner

from findplus.cli.main import main
from findplus.providers import apple_findmy as apple_pkg
from findplus.providers.apple_findmy import auth as auth_mod

_GOOGLE_ONLY_PHRASES = (
    "Google sign-in",
    "Chrome will open",
    "pkill -f chrome",
    "Android (AAS)",
)


def test_apple_provider_never_shows_google_wording(tmp_db, monkeypatch) -> None:
    """Extra installed: the Apple preamble runs, and no Google wording appears."""
    monkeypatch.setattr(apple_pkg, "is_available", lambda: (True, ""))
    monkeypatch.setattr(auth_mod, "sign_in_interactive", lambda settings: None)
    result = CliRunner().invoke(main, ["auth", "--provider", "apple-find-my"])
    for phrase in _GOOGLE_ONLY_PHRASES:
        assert phrase not in result.output, f"Google-only text leaked: {phrase!r}"
    assert "Apple Find My sign-in" in result.output
    assert result.exit_code == 0


def test_apple_provider_without_extra_prints_install_hint(tmp_db, monkeypatch) -> None:
    """Extra absent: the guard exits 1 with the hint and no Google wording."""
    monkeypatch.setattr(apple_pkg, "is_available", lambda: (False, "pip install 'findplus[apple]'"))
    result = CliRunner().invoke(main, ["auth", "--provider", "apple-find-my"])
    assert result.exit_code == 1
    assert "Apple provider not installed" in result.output
    assert "pip install 'findplus[apple]'" in result.output
    for phrase in _GOOGLE_ONLY_PHRASES:
        assert phrase not in result.output, f"Google-only text leaked: {phrase!r}"


def test_invalid_provider_rejected(tmp_db) -> None:
    result = CliRunner().invoke(main, ["auth", "--provider", "bogus-provider"])
    assert result.exit_code != 0
    assert "Invalid value" in result.output or "invalid choice" in result.output.lower()


def test_default_provider_still_shows_google_wording(tmp_db) -> None:
    """Regression guard: the fix must not remove the Google preamble either."""
    result = CliRunner().invoke(main, ["auth"], input="n\n")
    assert "Google sign-in" in result.output

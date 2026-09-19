"""`check_providers` (CF23): registry-based, per-provider status.

Purpose    : Cover what test_doctor.py's line cap pushed out here — the Google
             account name flowing through, and the Apple honesty line.
Constraints: Every check runs against tmp_db's isolated state dir, never the
             real ~/.findplus.
"""

from __future__ import annotations

import json


def test_check_providers_reports_the_google_account(tmp_db) -> None:
    """CF22/CF23: signing in to Google must flip the check and name the account,
    the same email GET /api/providers reports."""
    from findplus.cli.doctor import check_providers
    from findplus.config import get_settings

    settings = get_settings()
    settings.ensure_dirs()
    settings.secrets_file.write_text(json.dumps({"username": "kid@example.com"}))

    c = check_providers()
    assert c.passed is True
    assert "google-find-hub: signed-in (kid@example.com)" in c.detail


def test_check_providers_includes_the_apple_honesty_line(tmp_db) -> None:
    """CF23: apple-find-my must appear (it is always registered) with its
    honesty sentence, even when nobody has signed in to it."""
    from findplus.cli.doctor import check_providers
    from findplus.honesty import APPLE

    c = check_providers()
    assert "apple-find-my:" in c.detail
    assert APPLE in c.detail


def test_check_providers_never_raises_on_a_broken_provider(tmp_db, monkeypatch) -> None:
    """A provider whose is_available()/is_authenticated() throws is reported as
    an error line, not a crashed doctor run (mirrors routes_providers.py)."""
    from findplus.cli.doctor import check_providers
    from findplus.providers import base as provider_base

    class _Boom:
        name = "boom"
        display_name = "Boom"

        def is_available(self):
            raise RuntimeError("kaboom")

    monkeypatch.setattr(provider_base, "available_providers", lambda: ["boom"])
    monkeypatch.setattr(provider_base, "get_provider", lambda name: _Boom())

    c = check_providers()
    assert c.passed is False
    assert "boom: error (kaboom)" in c.detail

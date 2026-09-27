"""Fakes for the main-Chrome Google sign-in tests (token_signin.py and its route).

Purpose    : One place that points the vendored credential store at the test's
             own state dir and replaces the only two things that would reach
             Google: `gpsoauth.exchange_token` and `Auth.fcm_receiver.FcmReceiver`.
Constraints: No network (the autouse socket guard would refuse it anyway), no
             real ~/.findplus. Every patch goes through monkeypatch, so the
             vendor module attributes are restored after each test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

#: A realistic-looking value that must never appear in a file, log or response.
TOKEN = "oauth2_4/0AVGzR1SECRET-never-stored"
EMAIL = "kid@example.com"
AAS = "aas_et/long-lived-token"
ANDROID_ID = 0x3A1B2C3D


def isolate_store(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Re-run ensure_gfmt_importable() against this test's state dir; undo after."""
    from findplus.config import get_settings
    from findplus.providers.findhub.bootstrap import ensure_gfmt_importable as on_path
    from findplus.providers.google_findhub import bootstrap

    on_path()
    import Auth.token_cache as token_cache

    monkeypatch.setattr(bootstrap, "_ready", False)
    # Same-value setattr: records the current functions so monkeypatch puts
    # them back after ensure_gfmt_importable() rebinds them for this test.
    monkeypatch.setattr(token_cache, "_get_secrets_file", token_cache._get_secrets_file)
    monkeypatch.setattr(token_cache, "set_cached_value", token_cache.set_cached_value)
    return get_settings().secrets_file


class FakeFcmReceiver:
    """Upstream's singleton, minus the push connection."""

    android_id: ClassVar[object] = ANDROID_ID
    credentials: ClassVar[dict | None] = {"gcm": {"android_id": ANDROID_ID}}

    def get_android_id(self) -> object:
        return self.android_id


def install_google_fakes(
    monkeypatch: pytest.MonkeyPatch, response: dict | None = None, error: Exception | None = None
) -> list[tuple]:
    """Fake the exchange; returns the list of (email, token, android_id) calls."""
    import Auth.fcm_receiver as fcm_receiver
    import gpsoauth

    calls: list[tuple] = []
    answer = {"Token": AAS, "Email": EMAIL} if response is None else response

    def exchange(email, token, android_id, *args, **kwargs):
        calls.append((email, token, android_id))
        if error is not None:
            raise error
        return answer

    monkeypatch.setattr(fcm_receiver, "FcmReceiver", FakeFcmReceiver)
    monkeypatch.setattr(gpsoauth, "exchange_token", exchange)
    return calls


def read_store(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}

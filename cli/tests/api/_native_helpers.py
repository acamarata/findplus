"""Shared fakes for the in-app sign-in window suites (no Google, no vendor, no network)."""

from __future__ import annotations

from findplus.providers.google_findhub import native_flow
from findplus.providers.google_findhub.token_signin import (
    MSG_REJECTED,
    MSG_UNREACHABLE,
    GoogleUnreachableError,
    TokenRejectedError,
)
from findplus.providers.google_findhub.unlock import SharedKeyParseError

#: Exactly what the desktop shell sends on every ingest post (contract §2).
SHELL_HEADERS = {"Origin": "http://127.0.0.1:8647", "X-FindPlus-Client": "signin-window"}

FAKE_UNLOCK_URL = "https://accounts.google.com/encryption/unlock/android?kdi=AAAA"


def fake_google(
    monkeypatch,
    *,
    signed_in: bool = True,
    needs_unlock: bool = False,
    token_error: str | None = None,
    keys_error: bool = False,
) -> dict[str, list]:
    """Patch every Google-facing name native_flow calls. Returns the call log."""
    calls: dict[str, list] = {"token": [], "keys": []}
    state = {"unlocked": not needs_unlock}

    def sign_in(email, token, require_email=True):
        if token_error == "rejected":
            raise TokenRejectedError(MSG_REJECTED)
        if token_error == "unreachable":
            raise GoogleUnreachableError(MSG_UNREACHABLE)
        calls["token"].append((email, token, require_email))
        return "kid@example.com"

    def store(keys):
        if keys_error:
            raise SharedKeyParseError("Find+ could not find the location key in that unlock.")
        calls["keys"].append(keys)
        state["unlocked"] = True

    monkeypatch.setattr(native_flow, "sign_in_with_oauth_token", sign_in)
    monkeypatch.setattr(native_flow, "store_vault_keys", store)
    monkeypatch.setattr(native_flow, "unlock_url", lambda: FAKE_UNLOCK_URL)
    monkeypatch.setattr(native_flow, "has_google_session", lambda: signed_in)
    monkeypatch.setattr(native_flow, "needs_shared_key", lambda: not state["unlocked"])
    monkeypatch.setattr(native_flow, "has_shared_key", lambda: state["unlocked"])
    monkeypatch.setattr(
        native_flow, "stored_account_email", lambda: "kid@example.com" if signed_in else None
    )
    return calls

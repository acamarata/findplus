"""GoogleFindHubProvider.describe_auth() (CF22): the signed-in account email.

Purpose    : /api/providers pins `"account": str|null` (api-contract.md). This
             covers `describe_auth()` and its backing `stored_account_email()`
             in isolation, split out of test_google_findhub.py to stay under
             the file line cap.
Constraints: Tests never touch the real ~/.findplus; `tmp_db` isolates
             FINDPLUS_STATE_DIR per test. No network, no vendor import needed —
             stored_account_email() reads secrets.json directly.
"""

from __future__ import annotations

import json


def test_describe_auth_reports_no_account_when_never_signed_in(tmp_db) -> None:
    """No secrets.json at all -> account is None, not a KeyError/crash."""
    from findplus.providers.google_findhub.provider import GoogleFindHubProvider

    info = GoogleFindHubProvider().describe_auth()
    assert info == {"provider": "google-find-hub", "account": None}


def test_describe_auth_reports_the_stored_account_email(tmp_db) -> None:
    """/api/providers must report the signed-in Google account, read from the
    'username' key GoogleFindMyTools' token_cache persists in secrets.json."""
    from findplus.config import get_settings
    from findplus.providers.google_findhub.provider import GoogleFindHubProvider

    settings = get_settings()
    settings.ensure_dirs()
    settings.secrets_file.write_text(json.dumps({"username": "kid@example.com", "aas_et": "x"}))

    info = GoogleFindHubProvider().describe_auth()
    assert info == {"provider": "google-find-hub", "account": "kid@example.com"}


def test_describe_auth_never_leaks_other_secrets(tmp_db) -> None:
    """Only 'account' is surfaced; token/session material never appears."""
    from findplus.config import get_settings
    from findplus.providers.google_findhub.provider import GoogleFindHubProvider

    settings = get_settings()
    settings.ensure_dirs()
    settings.secrets_file.write_text(
        json.dumps({"username": "kid@example.com", "aas_et": "super-secret-token"})
    )

    info = GoogleFindHubProvider().describe_auth()
    assert set(info.keys()) == {"provider", "account"}
    assert "super-secret-token" not in json.dumps(info)


def test_stored_account_email_handles_unreadable_secrets(tmp_db) -> None:
    """Malformed secrets.json must not raise; account is just None."""
    from findplus.config import get_settings
    from findplus.providers.google_findhub.bootstrap import stored_account_email

    settings = get_settings()
    settings.ensure_dirs()
    settings.secrets_file.write_text("{not json")

    assert stored_account_email() is None


def test_stored_account_email_ignores_empty_username(tmp_db) -> None:
    """An empty-string username (upstream writes '' before a real sign-in
    completes) must read back as None, not as a falsy-but-present account."""
    from findplus.config import get_settings
    from findplus.providers.google_findhub.bootstrap import stored_account_email

    settings = get_settings()
    settings.ensure_dirs()
    settings.secrets_file.write_text(json.dumps({"username": ""}))

    assert stored_account_email() is None

"""has_google_session(): "signed in to Google" means a session, not a file.

Purpose    : A failed or cancelled sign-in left secrets.json holding only
             `fcm_credentials` (FcmReceiver writes them before the token
             exchange), and the card then claimed "signed in" with no account.
             Signed in now means the store holds an `aas_token` AND a username,
             everywhere: the client, /api/auth/status, doctor, `findplus start`.
Constraints: tmp_db isolates FINDPLUS_STATE_DIR; nothing imports the vendor.
"""

from __future__ import annotations

import json

import pytest

from findplus.api import create_app
from tests.api._auth_helpers import SAME_ORIGIN_HEADERS

FCM_ONLY = {"fcm_credentials": {"gcm": {"android_id": 1}}}
SESSION = {"aas_token": "aas_et/x", "username": "kid@example.com", **FCM_ONLY}


def _write(payload) -> None:
    from findplus.config import get_settings

    settings = get_settings()
    settings.ensure_dirs()
    text = payload if isinstance(payload, str) else json.dumps(payload)
    settings.secrets_file.write_text(text)


@pytest.mark.parametrize(
    "payload",
    [
        FCM_ONLY,
        {"username": "kid@example.com"},
        {"aas_token": "aas_et/x"},
        {"aas_token": "", "username": "kid@example.com"},
        "{}",
        "{not json",
        "[1, 2]",
    ],
    ids=["fcm-only", "username-only", "token-only", "empty-token", "empty", "corrupt", "list"],
)
def test_a_store_without_a_session_is_signed_out(tmp_db, payload) -> None:
    from findplus.providers.google_findhub.bootstrap import (
        describe_stored_auth,
        has_google_session,
    )
    from findplus.providers.google_findhub.client import FindHubClient

    _write(payload)
    assert has_google_session() is False
    assert FindHubClient().is_authenticated() is False
    info = describe_stored_auth()
    assert info["exists"] is True and info["signed_in"] is False


def test_a_token_and_a_username_are_signed_in(tmp_db) -> None:
    from findplus.providers.google_findhub.bootstrap import (
        describe_stored_auth,
        has_google_session,
    )

    _write(SESSION)
    assert has_google_session() is True
    assert describe_stored_auth()["signed_in"] is True


def test_the_fcm_only_file_shows_signed_out_in_status_and_doctor(tmp_db) -> None:
    from fastapi.testclient import TestClient

    from findplus.cli.doctor import check_providers

    _write(FCM_ONLY)
    rows = TestClient(create_app()).get("/api/auth/status").json()["providers"]
    google = next(row for row in rows if row["id"] == "google-find-hub")
    assert google["signed_in"] is False and google["account"] is None
    assert "google-find-hub: not signed-in" in check_providers().detail


def test_sign_out_still_removes_an_fcm_only_file(tmp_db) -> None:
    """Disconnect must clear the leftover file even though it never counted as signed in."""
    from fastapi.testclient import TestClient

    from findplus.config import get_settings

    _write(FCM_ONLY)
    res = TestClient(create_app()).delete("/api/auth/google-find-hub", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 204
    assert not get_settings().secrets_file.exists()


def test_start_treats_an_fcm_only_file_as_not_signed_in(tmp_db) -> None:
    from click.testing import CliRunner

    from findplus.cli.main import main

    _write(FCM_ONLY)
    result = CliRunner().invoke(main, ["start", "--no-open"])
    assert "Find+ is not signed in yet." in result.output
    assert result.exit_code != 0

"""A revoked Google sign-in reads as "signed out", never as a vague poll error.

Purpose    : The vendored token step raises `KeyError('Auth')` when Google rejects
             the saved login. That must become AuthRequiredError (status
             `auth_error`), mark the store, and flip every "signed in" read to
             false until the user signs in again; a transient Google error must
             stay a retryable error and must not sign anyone out.
Constraints: gpsoauth is faked (no network), isolated state dir.
"""

from __future__ import annotations

import json

import pytest

from findplus.providers.google_findhub import bootstrap, revoked
from findplus.providers.google_findhub.types import AuthRequiredError, FindHubError
from tests.providers._google_token_helpers import isolate_store

SESSION = {"aas_token": "aas_et/x", "username": "kid@example.com"}


def _fake_oauth(monkeypatch, response: dict) -> None:
    import gpsoauth

    monkeypatch.setattr(gpsoauth, "perform_oauth", lambda *a, **k: response)
    revoked.install_oauth_probe()


def _token_step() -> None:
    import gpsoauth

    gpsoauth.perform_oauth("u", "t", 1)["Auth"]


def _store(monkeypatch) -> object:
    store = isolate_store(monkeypatch)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(SESSION))
    return store


def test_a_dead_login_becomes_a_typed_sign_in_again(tmp_db, monkeypatch) -> None:
    store = _store(monkeypatch)
    _fake_oauth(monkeypatch, {"Error": "BadAuthentication"})
    with pytest.raises(AuthRequiredError) as caught, revoked.revoked_as_auth_error():
        _token_step()
    assert "Sign in again" in str(caught.value)
    assert json.loads(store.read_text())["auth_revoked"] == "1"
    assert bootstrap.has_google_session() is False


def test_a_transient_google_error_is_retryable_and_signs_nobody_out(tmp_db, monkeypatch) -> None:
    store = _store(monkeypatch)
    _fake_oauth(monkeypatch, {"Error": "ServiceUnavailable"})
    with pytest.raises(FindHubError) as caught, revoked.revoked_as_auth_error():
        _token_step()
    assert not isinstance(caught.value, AuthRequiredError)
    assert "auth_revoked" not in json.loads(store.read_text())
    assert bootstrap.has_google_session() is True


def test_other_key_errors_pass_through(tmp_db, monkeypatch) -> None:
    _store(monkeypatch)
    with pytest.raises(KeyError), revoked.revoked_as_auth_error():
        raise KeyError("something_else")


def test_signing_in_again_clears_the_mark(tmp_db, monkeypatch) -> None:
    store = _store(monkeypatch)
    _fake_oauth(monkeypatch, {"Error": "BadAuthentication"})
    with pytest.raises(AuthRequiredError), revoked.revoked_as_auth_error():
        _token_step()
    from findplus.providers.google_findhub.session import save_session

    save_session("aas_et/new", "kid@example.com")
    assert bootstrap.has_google_session() is True
    assert not json.loads(store.read_text()).get("auth_revoked")


def test_the_status_api_reports_signed_out_while_revoked(tmp_db, monkeypatch) -> None:
    store = _store(monkeypatch)
    store.write_text(json.dumps({**SESSION, "auth_revoked": "1"}))
    from findplus.providers.auth_status import build_auth_status

    google = next(p for p in build_auth_status()["providers"] if p["id"] == "google-find-hub")
    assert google["signed_in"] is False
    assert "reauth" in google["needs"]

"""token_signin.py: sign in with an `oauth_token` copied from the user's own Chrome.

Purpose    : The exchange the vendored flow runs, reused without editing it:
             validation, the stored session (aas_token + username, 0600), the
             token never stored or logged, failure mapping, the timeout, and an
             account switch dropping the old account's E2EE keys.
Constraints: gpsoauth and FcmReceiver are faked (_google_token_helpers.py). No
             network, no real ~/.findplus, no browser.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import threading

import pytest
import requests

from findplus.providers.google_findhub import token_signin
from findplus.providers.google_findhub.bootstrap import has_google_session
from tests.providers._google_token_helpers import (
    AAS,
    ANDROID_ID,
    EMAIL,
    TOKEN,
    FakeFcmReceiver,
    install_google_fakes,
    isolate_store,
    read_store,
)


@pytest.mark.parametrize(
    "raw",
    [TOKEN, f"  {TOKEN}\n", f'"{TOKEN}"', f"'{TOKEN}'", f"\t{TOKEN[:12]}\n{TOKEN[12:]} "],
)
def test_pasted_tokens_are_trimmed_of_whitespace_and_quotes(raw) -> None:
    assert token_signin.clean_oauth_token(raw) == TOKEN


@pytest.mark.parametrize("raw", ["", "oauth2_4/", "ya29.abc", "oauth2rt_1/abc", None])
def test_anything_but_an_oauth2_4_value_is_refused(raw) -> None:
    with pytest.raises(token_signin.InvalidInputError, match="starts with oauth2_4/"):
        token_signin.clean_oauth_token(raw)


@pytest.mark.parametrize("raw", ["", "kid", "kid@", "kid@example", "a b@example.com"])
def test_a_malformed_email_is_refused(raw) -> None:
    with pytest.raises(token_signin.InvalidInputError, match="Google email"):
        token_signin.clean_email(raw)


def test_success_stores_the_session_and_never_the_oauth_token(
    tmp_db, monkeypatch, caplog, capsys
) -> None:
    store = isolate_store(monkeypatch)
    calls = install_google_fakes(monkeypatch)
    caplog.set_level(logging.DEBUG)

    account = token_signin.sign_in_with_oauth_token(f" {EMAIL} ", f'"{TOKEN}"\n')

    assert account == EMAIL
    assert calls == [(EMAIL, TOKEN, ANDROID_ID)]
    data = read_store(store)
    assert data["aas_token"] == AAS
    assert data["username"] == EMAIL
    assert TOKEN not in store.read_text()
    assert TOKEN not in caplog.text
    assert TOKEN not in capsys.readouterr().out
    assert has_google_session()


@pytest.mark.posix_only
def test_the_store_is_0600(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    install_google_fakes(monkeypatch)
    token_signin.sign_in_with_oauth_token(EMAIL, TOKEN)
    assert stat.S_IMODE(os.stat(store).st_mode) == 0o600


def test_googles_own_email_wins_over_the_typed_one(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    install_google_fakes(monkeypatch, response={"Token": AAS, "Email": "Real@Example.com"})
    assert token_signin.sign_in_with_oauth_token(EMAIL, TOKEN) == "Real@Example.com"
    assert read_store(store)["username"] == "Real@Example.com"


def test_without_an_email_in_the_answer_the_typed_one_is_kept(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    install_google_fakes(monkeypatch, response={"Token": AAS})
    assert token_signin.sign_in_with_oauth_token(EMAIL, TOKEN) == EMAIL
    assert read_store(store)["username"] == EMAIL


def test_bad_authentication_is_a_friendly_rejection_and_stores_nothing(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    install_google_fakes(monkeypatch, response={"Error": "BadAuthentication"})
    with pytest.raises(token_signin.TokenRejectedError) as caught:
        token_signin.sign_in_with_oauth_token(EMAIL, TOKEN)
    assert str(caught.value) == token_signin.MSG_REJECTED
    assert "aas_token" not in read_store(store)
    assert not has_google_session()


def test_a_network_failure_says_google_could_not_be_reached(tmp_db, monkeypatch) -> None:
    isolate_store(monkeypatch)
    install_google_fakes(monkeypatch, error=requests.ConnectionError(f"boom {TOKEN}"))
    with pytest.raises(token_signin.GoogleUnreachableError) as caught:
        token_signin.sign_in_with_oauth_token(EMAIL, TOKEN)
    assert str(caught.value) == token_signin.MSG_UNREACHABLE
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_an_unexpected_error_never_surfaces_its_own_text(tmp_db, monkeypatch) -> None:
    isolate_store(monkeypatch)
    install_google_fakes(monkeypatch, error=ValueError(f"parse failed near {TOKEN}"))
    with pytest.raises(token_signin.TokenSignInError) as caught:
        token_signin.sign_in_with_oauth_token(EMAIL, TOKEN)
    assert str(caught.value) == token_signin.MSG_FAILED


def test_a_hung_exchange_times_out(tmp_db, monkeypatch) -> None:
    isolate_store(monkeypatch)
    release = threading.Event()
    monkeypatch.setattr(token_signin, "_exchange", lambda e, t: release.wait(5) or {})
    try:
        with pytest.raises(token_signin.GoogleUnreachableError):
            token_signin.sign_in_with_oauth_token(EMAIL, TOKEN, timeout=0.05)
    finally:
        release.set()


def test_a_first_run_android_id_comes_from_the_fresh_credentials(tmp_db, monkeypatch) -> None:
    """Upstream's get_android_id() returns None right after registering."""
    isolate_store(monkeypatch)
    calls = install_google_fakes(monkeypatch)
    monkeypatch.setattr(FakeFcmReceiver, "android_id", None)
    token_signin.sign_in_with_oauth_token(EMAIL, TOKEN)
    assert calls[0][2] == ANDROID_ID


def test_switching_accounts_drops_the_old_accounts_keys(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    store.parent.mkdir(parents=True, exist_ok=True)
    old = {"username": "old@example.com", "aas_token": "x", "owner_key": "k", "shared_key": "s"}
    store.write_text(json.dumps({**old, "fcm_credentials": {"gcm": {}}}))
    install_google_fakes(monkeypatch)

    token_signin.sign_in_with_oauth_token(EMAIL, TOKEN)

    data = read_store(store)
    assert "owner_key" not in data and "shared_key" not in data
    assert data["fcm_credentials"] == {"gcm": {}}
    assert data["username"] == EMAIL


def test_the_same_account_keeps_its_keys(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({"username": EMAIL, "owner_key": "k"}))
    install_google_fakes(monkeypatch)
    token_signin.sign_in_with_oauth_token(EMAIL.upper(), TOKEN)
    assert read_store(store)["owner_key"] == "k"

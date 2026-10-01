"""A failed helper hand-off keeps its state for a retry and tells the card why.

Purpose    : a transient exchange failure (502) must not burn the single-use
             state, a rejected token is reported in plain words through
             /api/auth/status, a success burns the state, and two concurrent
             attempts on one state cannot both run.
"""

from __future__ import annotations

import pytest

from findplus.api import _routes_auth_google_helper as helper
from findplus.providers.google_findhub import helper_state as hs
from findplus.providers.google_findhub.token_signin import (
    MSG_REJECTED,
    GoogleUnreachableError,
    TokenRejectedError,
)

EXT = {"Origin": f"chrome-extension://{hs.EXTENSION_ID}"}
TOKEN_PATH = "/api/auth/google/helper/token"


@pytest.fixture(autouse=True)
def _reset():
    hs.reset_for_tests()
    yield
    hs.reset_for_tests()


def _post(client, state):
    return client.post(TOKEN_PATH, json={"state": state, "oauth_token": "t"}, headers=EXT)


def _outcome(client):
    return client.get("/api/auth/status").json()["google_helper_outcome"]


def test_a_502_keeps_the_state_so_the_retry_succeeds(auth_client, monkeypatch) -> None:
    calls = []

    def exchange(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise GoogleUnreachableError("Couldn't reach Google. Check your internet connection.")
        return "kid@example.com"

    monkeypatch.setattr(helper, "sign_in_with_oauth_token", exchange)
    state = hs.create_state(hs.KIND_SIGNIN)
    first = _post(auth_client, state)
    assert first.status_code == 502
    assert "reach Google" in first.json()["detail"]
    assert _outcome(auth_client) == {
        "kind": "signin",
        "ok": False,
        "message": "Couldn't reach Google. Check your internet connection.",
    }
    second = _post(auth_client, state)
    assert second.status_code == 200
    assert _outcome(auth_client)["ok"] is True
    assert _post(auth_client, state).status_code == 403  # burned only by success


def test_a_rejected_token_is_reported_in_plain_words(auth_client, monkeypatch) -> None:
    def boom(*a, **k):
        raise TokenRejectedError(MSG_REJECTED)

    monkeypatch.setattr(helper, "sign_in_with_oauth_token", boom)
    assert _post(auth_client, hs.create_state(hs.KIND_SIGNIN)).status_code == 400
    assert _outcome(auth_client)["message"] == MSG_REJECTED


def test_an_unexpected_error_never_leaks_its_text(auth_client, monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("secret oauth2_4/abc in a traceback")

    monkeypatch.setattr(helper, "sign_in_with_oauth_token", boom)
    res = _post(auth_client, hs.create_state(hs.KIND_SIGNIN))
    assert res.status_code == 502
    assert "oauth2_4" not in res.text
    assert "oauth2_4" not in str(_outcome(auth_client))


def test_a_stale_state_records_an_expired_message(auth_client) -> None:
    assert _post(auth_client, "nope").status_code == 403
    assert "expired" in _outcome(auth_client)["message"]


def test_a_new_begin_clears_the_previous_outcome(auth_client) -> None:
    _post(auth_client, "nope")
    hs.create_state(hs.KIND_SIGNIN)
    assert _outcome(auth_client) is None


def test_two_concurrent_attempts_on_one_state_cannot_both_run() -> None:
    state = hs.create_state(hs.KIND_SIGNIN)
    assert hs.begin_exchange(hs.KIND_SIGNIN, state) is True
    assert hs.begin_exchange(hs.KIND_SIGNIN, state) is False
    hs.end_exchange(state, ok=False)
    assert hs.begin_exchange(hs.KIND_SIGNIN, state) is True
    hs.end_exchange(state, ok=True)
    assert hs.begin_exchange(hs.KIND_SIGNIN, state) is False


def test_the_wrong_kind_cannot_claim_a_state() -> None:
    state = hs.create_state(hs.KIND_SIGNIN)
    assert hs.begin_exchange(hs.KIND_UNLOCK, state) is False


def test_a_failed_unlock_keeps_its_state_and_reports(auth_client, monkeypatch) -> None:
    from findplus.providers.google_findhub.unlock import MSG_NO_VAULT_KEY, SharedKeyParseError

    def boom(v):
        raise SharedKeyParseError(MSG_NO_VAULT_KEY)

    monkeypatch.setattr(helper, "store_vault_keys", boom)
    state = hs.create_state(hs.KIND_UNLOCK)
    res = auth_client.post(
        "/api/auth/google/helper/unlock", json={"state": state, "vault_keys": "{}"}, headers=EXT
    )
    assert res.status_code == 400
    assert _outcome(auth_client) == {"kind": "unlock", "ok": False, "message": MSG_NO_VAULT_KEY}
    assert hs.begin_exchange(hs.KIND_UNLOCK, state) is True

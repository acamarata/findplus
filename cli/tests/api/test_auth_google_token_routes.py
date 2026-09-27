"""POST /api/auth/google/open and /token: the main-Chrome Google sign-in over HTTP.

Purpose    : Status codes, the Origin guard, the stored session, failure
             mapping, and the token never appearing in a response, a log line
             or secrets.json. After a token sign-in the provider must read as
             signed in with the account, and Disconnect must still work.
Constraints: gpsoauth and FcmReceiver are faked; the autouse no_real_browser
             guard stands in for Chrome. No network, no real ~/.findplus.
"""

from __future__ import annotations

import logging

import pytest
import requests
from fastapi.testclient import TestClient

from findplus.api import _routes_auth_google_token as token_routes
from findplus.providers.google_findhub import token_signin
from findplus.providers.google_findhub.open_signin import EMBEDDED_SETUP_URL, BrowserOpenError
from tests.api._auth_helpers import EVIL, SAME_ORIGIN_HEADERS
from tests.providers._google_token_helpers import (
    AAS,
    EMAIL,
    TOKEN,
    install_google_fakes,
    isolate_store,
    read_store,
)

OPEN = "/api/auth/google/open"
TOKEN_ROUTE = "/api/auth/google/token"
BODY = {"email": EMAIL, "oauth_token": TOKEN}


def _google_row(client: TestClient) -> dict:
    rows = client.get("/api/auth/status").json()["providers"]
    return next(row for row in rows if row["id"] == "google-find-hub")


# --------------------------------------------------------------------- open
def test_open_names_the_browser_and_the_page(auth_client, monkeypatch, no_real_browser) -> None:
    monkeypatch.setattr(
        "findplus.providers.google_findhub.open_signin.find_google_chrome", lambda: "/x/chrome"
    )
    res = auth_client.post(OPEN, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 200
    assert res.json() == {"browser": "chrome", "url": EMBEDDED_SETUP_URL}
    assert no_real_browser == [EMBEDDED_SETUP_URL]


def test_open_that_cannot_open_anything_is_503_in_words(auth_client, monkeypatch) -> None:
    def fail():
        raise BrowserOpenError("Find+ could not open a browser.")

    monkeypatch.setattr(token_routes, "open_sign_in_page", fail)
    res = auth_client.post(OPEN, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 503
    assert res.json() == {"detail": "Find+ could not open a browser."}


@pytest.mark.parametrize("route", [OPEN, TOKEN_ROUTE])
@pytest.mark.parametrize("headers", [{}, {"Origin": EVIL}], ids=["headerless", "foreign"])
def test_both_routes_refuse_a_request_without_same_origin_proof(
    auth_client, monkeypatch, no_real_browser, route, headers
) -> None:
    calls = []
    monkeypatch.setattr(token_routes, "sign_in_with_oauth_token", lambda *a: calls.append(a))
    res = auth_client.post(route, json=BODY, headers=headers)
    assert res.status_code == 403
    assert TOKEN not in res.text
    assert calls == [] and no_real_browser == []


# -------------------------------------------------------------------- token
def test_token_signs_in_and_the_provider_reports_the_account(
    auth_client, monkeypatch, caplog
) -> None:
    store = isolate_store(monkeypatch)
    install_google_fakes(monkeypatch)
    caplog.set_level(logging.DEBUG)
    assert _google_row(auth_client)["signed_in"] is False

    res = auth_client.post(TOKEN_ROUTE, json=BODY, headers=SAME_ORIGIN_HEADERS)

    assert res.status_code == 200, res.text
    assert res.json() == {
        "state": "done",
        "account": EMAIL,
        "message": f"Authenticated as {EMAIL}.",
    }
    row = _google_row(auth_client)
    assert row["signed_in"] is True and row["account"] == EMAIL
    assert read_store(store)["aas_token"] == AAS
    for text in (res.text, store.read_text(), caplog.text):
        assert TOKEN not in text


def test_sign_out_after_a_token_sign_in(auth_client, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    install_google_fakes(monkeypatch)
    auth_client.post(TOKEN_ROUTE, json=BODY, headers=SAME_ORIGIN_HEADERS)
    res = auth_client.delete("/api/auth/google-find-hub", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 204
    assert not store.exists()
    assert _google_row(auth_client)["signed_in"] is False


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"email": "nope", "oauth_token": TOKEN}, "Google email"),
        ({"email": EMAIL, "oauth_token": "ya29.not-it"}, "starts with oauth2_4/"),
        ({"oauth_token": TOKEN}, "Google email"),
        ({}, "Google email"),
    ],
    ids=["bad-email", "bad-token", "missing-email", "empty"],
)
def test_invalid_input_is_422_in_words_and_never_echoed(auth_client, body, fragment) -> None:
    res = auth_client.post(TOKEN_ROUTE, json=body, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 422
    assert fragment in res.json()["detail"]
    assert TOKEN not in res.text


def test_a_wrongly_typed_field_never_echoes_the_body(auth_client) -> None:
    body = {"email": [EMAIL, TOKEN], "oauth_token": [TOKEN]}
    res = auth_client.post(TOKEN_ROUTE, json=body, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 422
    assert TOKEN not in res.text


@pytest.mark.parametrize(
    ("fakes", "status", "message"),
    [
        ({"response": {"Error": "BadAuthentication"}}, 400, token_signin.MSG_REJECTED),
        ({"error": requests.ConnectionError("down")}, 502, token_signin.MSG_UNREACHABLE),
        ({"error": RuntimeError(TOKEN)}, 500, token_signin.MSG_FAILED),
    ],
    ids=["rejected", "unreachable", "unexpected"],
)
def test_failures_map_to_plain_messages(auth_client, monkeypatch, fakes, status, message) -> None:
    store = isolate_store(monkeypatch)
    install_google_fakes(monkeypatch, **fakes)
    res = auth_client.post(TOKEN_ROUTE, json=BODY, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == status
    assert res.json() == {"detail": message}
    assert "aas_token" not in read_store(store)
    assert _google_row(auth_client)["signed_in"] is False

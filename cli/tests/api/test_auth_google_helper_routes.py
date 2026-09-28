"""The Chrome-helper daemon endpoints: begin, ingest (token/unlock), seen, pages.

Purpose    : origin pinning (only the pinned extension origin + a valid
             single-use state may ingest), begin opens a 127.0.0.1 page, the
             token/unlock exchange runs through the shared helpers (mocked), and
             the begin/success pages render. No browser, no vendor, no network.
"""

from __future__ import annotations

import pytest

from findplus.api import _routes_auth_google_helper as helper
from findplus.providers.google_findhub import helper_state as hs
from tests.api._auth_helpers import EVIL, SAME_ORIGIN_HEADERS

EXT_ORIGIN = f"chrome-extension://{hs.EXTENSION_ID}"
TOKEN_PATH = "/api/auth/google/helper/token"
UNLOCK_PATH = "/api/auth/google/helper/unlock"


@pytest.fixture(autouse=True)
def _reset():
    hs.reset_for_tests()
    yield
    hs.reset_for_tests()


@pytest.fixture
def no_browser(monkeypatch, no_real_browser):
    # no_real_browser (root conftest) already neutralises open_signin's launch.
    return no_real_browser


# ------------------------------------------------------------------- begin
def test_begin_opens_a_127_0_0_1_page_and_reports_the_browser(auth_client, no_browser) -> None:
    res = auth_client.post("/api/auth/google/helper/begin", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 202
    assert res.json()["browser"] in ("chrome", "default")
    assert no_browser and no_browser[0].startswith("http://127.0.0.1:")
    assert "/auth/google/begin?state=" in no_browser[0]


def test_unlock_begin_opens_the_unlock_page(auth_client, no_browser, monkeypatch) -> None:
    monkeypatch.setattr(helper, "open_sign_in_page", lambda url: no_browser.append(url) or "chrome")
    res = auth_client.post("/api/auth/google/helper/unlock-begin", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 202
    assert "/auth/google/unlock/begin?state=" in no_browser[-1]


@pytest.mark.parametrize("headers", [{}, {"Origin": EVIL}], ids=["headerless", "foreign"])
def test_begin_needs_same_origin_proof(auth_client, no_browser, headers) -> None:
    res = auth_client.post("/api/auth/google/helper/begin", headers=headers)
    assert res.status_code == 403
    assert no_browser == []


# ------------------------------------------------------------ token ingest
def test_token_from_the_pinned_extension_signs_in(auth_client, monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(
        helper,
        "sign_in_with_oauth_token",
        lambda email, token, require_email=True: (
            seen.update(email=email, token=token, req=require_email) or "kid@example.com"
        ),
    )
    state = hs.create_state(hs.KIND_SIGNIN)
    res = auth_client.post(
        TOKEN_PATH,
        json={"state": state, "oauth_token": "oauth2_4/abc"},
        headers={"Origin": EXT_ORIGIN},
    )
    assert res.status_code == 200
    assert res.json() == {"state": "done", "account": "kid@example.com"}
    assert seen == {"email": "", "token": "oauth2_4/abc", "req": False}  # empty email on purpose


def test_token_state_is_single_use(auth_client, monkeypatch) -> None:
    monkeypatch.setattr(helper, "sign_in_with_oauth_token", lambda *a, **k: "kid@example.com")
    state = hs.create_state(hs.KIND_SIGNIN)
    ok = auth_client.post(
        TOKEN_PATH, json={"state": state, "oauth_token": "t"}, headers={"Origin": EXT_ORIGIN}
    )
    assert ok.status_code == 200
    replay = auth_client.post(
        TOKEN_PATH, json={"state": state, "oauth_token": "t"}, headers={"Origin": EXT_ORIGIN}
    )
    assert replay.status_code == 403


@pytest.mark.parametrize(
    "origin", [None, "chrome-extension://someotherid", "http://127.0.0.1:8647", EVIL]
)
def test_token_refuses_any_other_origin(auth_client, monkeypatch, origin) -> None:
    called = []
    monkeypatch.setattr(helper, "sign_in_with_oauth_token", lambda *a, **k: called.append(1) or "x")
    state = hs.create_state(hs.KIND_SIGNIN)
    headers = {"Origin": origin} if origin else {}
    res = auth_client.post(TOKEN_PATH, json={"state": state, "oauth_token": "t"}, headers=headers)
    assert res.status_code == 403
    assert called == []


def test_token_with_a_wrong_state_is_403(auth_client, monkeypatch) -> None:
    called = []
    monkeypatch.setattr(helper, "sign_in_with_oauth_token", lambda *a, **k: called.append(1) or "x")
    res = auth_client.post(
        TOKEN_PATH, json={"state": "nope", "oauth_token": "t"}, headers={"Origin": EXT_ORIGIN}
    )
    assert res.status_code == 403
    assert called == []


def test_token_rejection_maps_to_400(auth_client, monkeypatch) -> None:
    from findplus.providers.google_findhub.token_signin import MSG_REJECTED, TokenRejectedError

    def boom(*a, **k):
        raise TokenRejectedError(MSG_REJECTED)

    monkeypatch.setattr(helper, "sign_in_with_oauth_token", boom)
    state = hs.create_state(hs.KIND_SIGNIN)
    res = auth_client.post(
        TOKEN_PATH, json={"state": state, "oauth_token": "t"}, headers={"Origin": EXT_ORIGIN}
    )
    assert res.status_code == 400
    assert res.json()["detail"] == MSG_REJECTED


# ----------------------------------------------------------- unlock ingest
def test_unlock_from_the_pinned_extension_stores_the_key(auth_client, monkeypatch) -> None:
    stored = {}
    monkeypatch.setattr(helper, "store_vault_keys", lambda v: stored.update(v=v))
    state = hs.create_state(hs.KIND_UNLOCK)
    res = auth_client.post(
        UNLOCK_PATH,
        json={"state": state, "vault_keys": {"finder_hw": []}},
        headers={"Origin": EXT_ORIGIN},
    )
    assert res.status_code == 200
    assert res.json() == {"state": "done"}
    assert stored["v"] == {"finder_hw": []}


def test_unlock_bad_keys_map_to_400(auth_client, monkeypatch) -> None:
    from findplus.providers.google_findhub.unlock import MSG_NO_VAULT_KEY, SharedKeyParseError

    def boom(v):
        raise SharedKeyParseError(MSG_NO_VAULT_KEY)

    monkeypatch.setattr(helper, "store_vault_keys", boom)
    state = hs.create_state(hs.KIND_UNLOCK)
    res = auth_client.post(
        UNLOCK_PATH, json={"state": state, "vault_keys": "{}"}, headers={"Origin": EXT_ORIGIN}
    )
    assert res.status_code == 400
    assert res.json()["detail"] == MSG_NO_VAULT_KEY


def test_a_signin_state_cannot_unlock(auth_client, monkeypatch) -> None:
    monkeypatch.setattr(helper, "store_vault_keys", lambda v: None)
    signin_state = hs.create_state(hs.KIND_SIGNIN)
    res = auth_client.post(
        UNLOCK_PATH,
        json={"state": signin_state, "vault_keys": "{}"},
        headers={"Origin": EXT_ORIGIN},
    )
    assert res.status_code == 403


# -------------------------------------------------------------- seen + pages
def test_seen_marks_the_helper_installed_in_status(auth_client) -> None:
    auth_client.post(
        "/api/auth/google/helper/seen", json={"state": "x"}, headers=SAME_ORIGIN_HEADERS
    )
    assert auth_client.get("/api/auth/status").json()["google_helper_installed"] is True


def test_the_begin_page_renders_with_the_target_and_state(auth_client) -> None:
    res = auth_client.get("/auth/google/begin?state=abc123")
    assert res.status_code == 200
    body = res.text
    assert "accounts.google.com/EmbeddedSetup" in body
    assert 'data-fp-state="abc123"' in body
    assert "/static/app/helper-begin.js" in body


def test_the_success_page_renders(auth_client) -> None:
    res = auth_client.get("/auth/google/success")
    assert res.status_code == 200
    assert "You can close this tab" in res.text

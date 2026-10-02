"""The in-app sign-in window's daemon routes: begin, token, unlock, progress, cancel.

Purpose    : begin mints a native state and describes the window; the token and
             unlock posts need the pinned shell headers plus that state; one
             state covers sign-in then unlock; the token never reaches a response
             or a log line. Google, Chrome and the vendor are all faked.
"""

from __future__ import annotations

import logging

import pytest

from findplus.providers.google_findhub import helper_state as hs
from findplus.providers.google_findhub import native_flow, native_progress
from tests.api._auth_helpers import EVIL, SAME_ORIGIN_HEADERS
from tests.api._native_helpers import SHELL_HEADERS, fake_google

BASE = "/api/auth/google/native"
SECRET = "oauth2_4/SECRET-VALUE-never-echoed"


@pytest.fixture(autouse=True)
def _reset():
    hs.reset_for_tests()
    native_progress.reset()
    yield
    hs.reset_for_tests()
    native_progress.reset()


def _begin(client, mode="signin") -> dict:
    res = client.post(f"{BASE}/begin", json={"mode": mode}, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 200, res.text
    return res.json()


# ------------------------------------------------------------------ begin
def test_begin_mints_a_native_state_and_describes_the_window(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch)
    body = _begin(auth_client)
    assert hs.state_kind(body["state"]) == hs.KIND_NATIVE_SIGNIN
    assert body["start_url"] == "https://accounts.google.com/EmbeddedSetup"
    assert body["unlock_url"].startswith("https://accounts.google.com/encryption/unlock/")
    assert body["window"]["label"] == "signin-google" and body["window"]["incognito"] is True
    assert body["expires_in"] == 600
    assert "127.0.0.1" not in str(body["allowed_hosts"])
    assert auth_client.get(f"{BASE}/progress").json()["phase"] == "connecting"


def test_a_second_begin_kills_the_first_state(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch)
    first = _begin(auth_client)["state"]
    _begin(auth_client)
    assert hs.state_kind(first) is None


def test_unlock_mode_needs_a_signed_in_account(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch, signed_in=False)
    res = auth_client.post(f"{BASE}/begin", json={"mode": "unlock"}, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 409 and res.json()["code"] == "not_signed_in"


@pytest.mark.parametrize("headers", [{}, {"Sec-Fetch-Site": "same-origin"}, {"Origin": EVIL}])
def test_begin_needs_a_loopback_origin(auth_client, monkeypatch, headers) -> None:
    fake_google(monkeypatch)
    res = auth_client.post(f"{BASE}/begin", json={}, headers=headers)
    assert res.status_code == 403
    assert hs._states == {}


# ------------------------------------------------------------------ token
def test_token_signs_in_and_needs_no_unlock(auth_client, monkeypatch) -> None:
    calls = fake_google(monkeypatch, needs_unlock=False)
    state = _begin(auth_client)["state"]
    res = auth_client.post(
        f"{BASE}/token", json={"state": state, "oauth_token": SECRET}, headers=SHELL_HEADERS
    )
    assert res.status_code == 200
    assert res.json() == {
        "result": "signed_in",
        "account": "kid@example.com",
        "needs_unlock": False,
    }
    assert calls["token"] == [("", SECRET, False)]
    assert hs.state_kind(state) is None  # burned
    progress = auth_client.get(f"{BASE}/progress").json()
    assert progress["phase"] == "success" and progress["account"] == "kid@example.com"
    assert progress["generation"] == 1


def test_one_state_covers_sign_in_then_unlock(auth_client, monkeypatch) -> None:
    calls = fake_google(monkeypatch, needs_unlock=True)
    state = _begin(auth_client)["state"]
    first = auth_client.post(
        f"{BASE}/token", json={"state": state, "oauth_token": SECRET}, headers=SHELL_HEADERS
    )
    assert first.json()["needs_unlock"] is True
    assert hs.state_kind(state) == hs.KIND_NATIVE_UNLOCK
    assert auth_client.get(f"{BASE}/progress").json()["phase"] == "needs_unlock"
    res = auth_client.post(
        f"{BASE}/unlock", json={"state": state, "vault_keys": {"k": 1}}, headers=SHELL_HEADERS
    )
    assert res.status_code == 200
    assert res.json() == {"result": "unlocked", "account": "kid@example.com"}
    assert calls["keys"] == [{"k": 1}]
    assert hs.state_kind(state) is None
    done = auth_client.get(f"{BASE}/progress").json()
    assert done["phase"] == "success" and done["unlocked"] is True
    assert done["message"] == "Connected as kid@example.com. Locations unlocked."


def test_a_replayed_token_post_is_refused(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch, needs_unlock=False)
    state = _begin(auth_client)["state"]
    body = {"state": state, "oauth_token": SECRET}
    assert auth_client.post(f"{BASE}/token", json=body, headers=SHELL_HEADERS).status_code == 200
    replay = auth_client.post(f"{BASE}/token", json=body, headers=SHELL_HEADERS)
    assert replay.status_code == 403 and replay.json()["code"] == "state_invalid"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        SAME_ORIGIN_HEADERS,
        {"Origin": "http://127.0.0.1:8647"},
        {"X-FindPlus-Client": "signin-window"},
        {"Origin": "http://localhost:8647", "X-FindPlus-Client": "signin-window"},
        {"Origin": "tauri://localhost", "X-FindPlus-Client": "signin-window"},
        {"Origin": "http://127.0.0.1:8647", "X-FindPlus-Client": "dashboard"},
    ],
)
def test_token_needs_the_pinned_shell_headers(auth_client, monkeypatch, headers) -> None:
    calls = fake_google(monkeypatch)
    state = _begin(auth_client)["state"]
    res = auth_client.post(
        f"{BASE}/token", json={"state": state, "oauth_token": SECRET}, headers=headers
    )
    assert res.status_code == 403
    assert calls["token"] == []
    assert hs.state_kind(state) == hs.KIND_NATIVE_SIGNIN  # untouched


def test_a_helper_state_cannot_drive_the_window_routes(auth_client, monkeypatch) -> None:
    calls = fake_google(monkeypatch)
    state = hs.create_state(hs.KIND_SIGNIN)
    res = auth_client.post(
        f"{BASE}/token", json={"state": state, "oauth_token": SECRET}, headers=SHELL_HEADERS
    )
    assert res.status_code == 403 and calls["token"] == []


@pytest.mark.parametrize(
    "error,status,code",
    [("rejected", 400, "token_rejected"), ("unreachable", 502, "google_unreachable")],
)
def test_refusals_are_plain_words_and_never_the_token(
    auth_client, monkeypatch, caplog, error, status, code
) -> None:
    fake_google(monkeypatch, token_error=error)
    caplog.set_level(logging.DEBUG)
    state = _begin(auth_client)["state"]
    res = auth_client.post(
        f"{BASE}/token", json={"state": state, "oauth_token": SECRET}, headers=SHELL_HEADERS
    )
    assert res.status_code == status and res.json()["code"] == code
    assert "token" not in res.json()["detail"].lower() and "cookie" not in res.json()["detail"]
    assert SECRET not in res.text and SECRET not in caplog.text
    assert hs.state_kind(state) == hs.KIND_NATIVE_SIGNIN  # kept for a retry
    assert auth_client.get(f"{BASE}/progress").json()["phase"] == "error"


def test_a_badly_typed_token_never_gets_a_422_echo(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch)
    state = _begin(auth_client)["state"]
    res = auth_client.post(
        f"{BASE}/token", json={"state": state, "oauth_token": {"x": SECRET}}, headers=SHELL_HEADERS
    )
    assert SECRET not in res.text


# ----------------------------------------------------------------- unlock
def test_unlock_refuses_a_different_account(auth_client, monkeypatch) -> None:
    calls = fake_google(monkeypatch)
    state = _begin(auth_client, "unlock")["state"]
    res = auth_client.post(
        f"{BASE}/unlock",
        json={"state": state, "vault_keys": "{}", "account_hint": "other@example.com"},
        headers=SHELL_HEADERS,
    )
    assert res.status_code == 409 and res.json()["code"] == "account_mismatch"
    assert calls["keys"] == []


def test_unlock_only_without_an_account_hint_saves_nothing(auth_client, monkeypatch) -> None:
    """Probe P3 (r12 #1): no hint means Find+ cannot know whose keys these are."""
    calls = fake_google(monkeypatch)
    state = _begin(auth_client, "unlock")["state"]
    for hint in (None, "", "   "):
        res = auth_client.post(
            f"{BASE}/unlock",
            json={"state": state, "vault_keys": "{}", "account_hint": hint},
            headers=SHELL_HEADERS,
        )
        assert res.status_code == 409 and res.json()["code"] == "account_unknown"
    assert calls["keys"] == []
    assert "could not tell which Google account" in res.json()["detail"]
    progress = auth_client.get(f"{BASE}/progress").json()
    assert progress["phase"] == "error" and progress["reason"] == "account_unknown"
    # The shell's own "failed" report afterwards keeps the daemon's words.
    body = {"state": state, "event": "failed", "reason": "other"}
    auth_client.post(f"{BASE}/event", json=body, headers=SHELL_HEADERS)
    after = auth_client.get(f"{BASE}/progress").json()
    assert after["phase"] == "error" and "could not tell which" in after["message"]


def test_unlock_only_with_the_right_hint_stores_the_keys(auth_client, monkeypatch) -> None:
    calls = fake_google(monkeypatch)
    state = _begin(auth_client, "unlock")["state"]
    res = auth_client.post(
        f"{BASE}/unlock",
        json={"state": state, "vault_keys": "{}", "account_hint": " Kid@Example.com "},
        headers=SHELL_HEADERS,
    )
    assert res.status_code == 200 and calls["keys"] == ["{}"]


def test_unlock_with_unusable_keys_says_so(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch, keys_error=True)
    state = _begin(auth_client, "unlock")["state"]
    res = auth_client.post(
        f"{BASE}/unlock",
        json={"state": state, "vault_keys": "junk", "account_hint": "kid@example.com"},
        headers=SHELL_HEADERS,
    )
    assert res.status_code == 400 and res.json()["code"] == "keys_rejected"
    assert "junk" not in res.text


def test_a_sign_in_state_cannot_unlock(auth_client, monkeypatch) -> None:
    calls = fake_google(monkeypatch)
    state = _begin(auth_client)["state"]
    res = auth_client.post(
        f"{BASE}/unlock", json={"state": state, "vault_keys": "{}"}, headers=SHELL_HEADERS
    )
    assert res.status_code == 403 and calls["keys"] == []


# ----------------------------------------------------------------- cancel
def test_cancel_kills_the_state_and_says_cancelled(auth_client, monkeypatch) -> None:
    calls = fake_google(monkeypatch)
    state = _begin(auth_client)["state"]
    res = auth_client.post(f"{BASE}/cancel", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 200 and res.json()["phase"] == "cancelled"
    late = auth_client.post(
        f"{BASE}/token", json={"state": state, "oauth_token": SECRET}, headers=SHELL_HEADERS
    )
    assert late.status_code == 403 and calls["token"] == []


def test_cancel_needs_an_origin_signal(auth_client) -> None:
    assert auth_client.post(f"{BASE}/cancel").status_code == 403


def test_the_unlock_url_comes_from_the_vendored_builder() -> None:
    """The unlock URL comes from the vendored builder, imported, never re-typed."""
    import inspect

    assert "get_security_domain_request_url" in inspect.getsource(native_flow.unlock_url)

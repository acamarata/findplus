"""Window events and blocked-page reports from the shell, and the fallback ladder.

Purpose    : opened/waiting/closed/failed/blocked move the card's phase; a
             blocked report (host, path, title class only) closes the flow,
             remembers the block for 7 days and points at the Chrome helper, or
             at the paste path when Chrome is missing. Lock: the four shell posts
             reach their own gate while locked; begin, progress and cancel 401.
"""

from __future__ import annotations

import pytest

from findplus.providers.google_findhub import helper_state as hs
from findplus.providers.google_findhub import native_progress
from tests.api._auth_helpers import SAME_ORIGIN_HEADERS
from tests.api._native_helpers import SHELL_HEADERS, fake_google

BASE = "/api/auth/google/native"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    hs.reset_for_tests()
    native_progress.reset()
    monkeypatch.setattr(native_progress, "_chrome_found", lambda: True)
    yield
    hs.reset_for_tests()
    native_progress.reset()


def _state(client, monkeypatch, mode="signin") -> str:
    fake_google(monkeypatch, needs_unlock=True)
    res = client.post(f"{BASE}/begin", json={"mode": mode}, headers=SAME_ORIGIN_HEADERS)
    return res.json()["state"]


def _event(client, state, event, reason=None):
    body = {"state": state, "event": event, "reason": reason}
    return client.post(f"{BASE}/event", json=body, headers=SHELL_HEADERS)


def _classify(client, state, host, path, title_class="normal"):
    body = {"state": state, "host": host, "path": path, "title_class": title_class}
    return client.post(f"{BASE}/classify", json=body, headers=SHELL_HEADERS)


def test_opened_then_waiting(auth_client, monkeypatch) -> None:
    state = _state(auth_client, monkeypatch)
    res = _event(auth_client, state, "opened")
    assert res.status_code == 200 and res.json()["phase"] == "waiting"
    assert res.json()["message"] == "Finish signing in in the Find+ window."


def test_unlock_only_window_waits_in_needs_unlock(auth_client, monkeypatch) -> None:
    state = _state(auth_client, monkeypatch, mode="unlock")
    assert _event(auth_client, state, "waiting").json()["phase"] == "needs_unlock"


def test_closing_the_window_is_a_cancel_and_kills_the_state(auth_client, monkeypatch) -> None:
    state = _state(auth_client, monkeypatch)
    assert _event(auth_client, state, "closed").json()["phase"] == "cancelled"
    assert hs.state_kind(state) is None
    assert native_progress.blocked_at() is None  # a cancel is not a block


@pytest.mark.parametrize("how", ["closed", "cancel"])
def test_stopping_after_sign_in_keeps_the_account_signed_in(auth_client, monkeypatch, how):
    state = _state(auth_client, monkeypatch)
    body = {"state": state, "oauth_token": "oauth2_4/x"}
    assert auth_client.post(f"{BASE}/token", json=body, headers=SHELL_HEADERS).json()[
        "needs_unlock"
    ]
    if how == "closed":
        _event(auth_client, state, "closed")
    else:
        auth_client.post(f"{BASE}/cancel", headers=SAME_ORIGIN_HEADERS)
    progress = auth_client.get(f"{BASE}/progress").json()
    assert progress["phase"] == "success" and progress["unlocked"] is False
    assert progress["message"] == "Connected as kid@example.com."
    assert hs.state_kind(state) is None


def test_failed_maps_its_reason_to_plain_words(auth_client, monkeypatch) -> None:
    state = _state(auth_client, monkeypatch)
    body = _event(auth_client, state, "failed", "load_failed").json()
    assert body["phase"] == "error" and "did not load" in body["message"]
    assert body["fallback"] == "use_helper"


def test_an_unknown_event_is_refused(auth_client, monkeypatch) -> None:
    state = _state(auth_client, monkeypatch)
    assert _event(auth_client, state, "stolen").status_code == 422


def test_events_need_a_live_state(auth_client) -> None:
    res = _event(auth_client, "nope", "opened")
    assert res.status_code == 403 and res.json()["code"] == "state_invalid"


def test_blocked_event_remembers_and_falls_back_to_the_helper(auth_client, monkeypatch) -> None:
    state = _state(auth_client, monkeypatch)
    body = _event(auth_client, state, "blocked", "stuck").json()
    assert body["phase"] == "blocked_embedded" and body["fallback"] == "use_helper"
    progress = auth_client.get(f"{BASE}/progress").json()
    assert progress["start_with"] == "helper" and progress["blocked_at"]
    assert hs.state_kind(state) is None


@pytest.mark.parametrize(
    "host,path,title,reason",
    [
        ("accounts.google.com", "/v3/signin/rejected", "normal", "rejected_page"),
        ("accounts.google.com", "/signin/rejected", "unknown", "rejected_page"),
        ("accounts.google.com", "/o/oauth2/disallowed_useragent", "normal", "disallowed_useragent"),
        ("accounts.google.com", "/v3/signin/identifier", "browser_not_secure", "rejected_page"),
        ("login.microsoftonline.com", "/common/oauth2", "normal", "outside_google"),
    ],
)
def test_classify_blocks(auth_client, monkeypatch, host, path, title, reason) -> None:
    state = _state(auth_client, monkeypatch)
    res = _classify(auth_client, state, host, path, title)
    assert res.status_code == 200
    assert res.json() == {
        "blocked": True,
        "reason": reason,
        "action": "close",
        "fallback": "use_helper",
    }
    assert auth_client.get(f"{BASE}/progress").json()["phase"] == "blocked_embedded"


def test_classify_lets_an_ordinary_page_continue(auth_client, monkeypatch) -> None:
    state = _state(auth_client, monkeypatch)
    res = _classify(auth_client, state, "accounts.google.com", "/v3/signin/challenge/pwd")
    assert res.json() == {"blocked": False, "reason": None, "action": "continue", "fallback": None}
    assert hs.state_kind(state) == hs.KIND_NATIVE_SIGNIN


@pytest.mark.parametrize(
    "host,path,title",
    [
        ("accounts.google.com", "/v3/signin?continue=x", "normal"),
        ("accounts.google.com", "/a#frag", "normal"),
        ("accounts.google.com", "no-slash", "normal"),
        ("https://accounts.google.com", "/", "normal"),
        ("accounts.google.com", "/" + "a" * 600, "normal"),
        ("accounts.google.com", "/", "Sign in - Google Accounts"),
        (["x"], "/", "normal"),
    ],
)
def test_classify_refuses_anything_but_host_and_path(auth_client, monkeypatch, host, path, title):
    state = _state(auth_client, monkeypatch)
    res = _classify(auth_client, state, host, path, title)
    assert res.status_code == 422 and res.json()["code"] == "bad_report"


def test_no_chrome_means_the_paste_path(auth_client, monkeypatch) -> None:
    monkeypatch.setattr(native_progress, "_chrome_found", lambda: False)
    state = _state(auth_client, monkeypatch)
    assert _event(auth_client, state, "blocked", "rejected_page").json()["fallback"] == "use_paste"


def test_helper_failing_after_a_block_means_the_paste_path(auth_client, monkeypatch) -> None:
    state = _state(auth_client, monkeypatch)
    _event(auth_client, state, "blocked", "rejected_page")
    hs.record_outcome(hs.KIND_SIGNIN, False, "nope")
    assert auth_client.get(f"{BASE}/progress").json()["fallback"] == "use_paste"


def test_a_block_is_forgotten_after_seven_days(auth_client, monkeypatch, tmp_path) -> None:
    from datetime import timedelta

    native_progress.remember_block("rejected_page")
    assert native_progress.blocked_at() is not None
    later = native_progress._now() + timedelta(days=7, minutes=1)
    monkeypatch.setattr(native_progress, "_now", lambda: later)
    assert native_progress.blocked_at() is None


def test_block_memory_file_is_private(tmp_db) -> None:
    native_progress.remember_block("stuck")
    path = native_progress._path()
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert "stuck" in path.read_text()


# ------------------------------------------------------------------- lock
@pytest.mark.parametrize("path", ["token", "unlock", "event", "classify"])
def test_shell_posts_reach_their_own_gate_while_locked(locked_client, path) -> None:
    res = locked_client.post(f"{BASE}/{path}", json={"state": "x"}, headers=SHELL_HEADERS)
    assert res.status_code == 403 and res.json()["code"] == "state_invalid"


@pytest.mark.parametrize(
    "method,path", [("POST", "begin"), ("POST", "cancel"), ("GET", "progress")]
)
def test_begin_progress_cancel_401_while_locked(locked_client, method, path) -> None:
    res = locked_client.request(method, f"{BASE}/{path}", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 401

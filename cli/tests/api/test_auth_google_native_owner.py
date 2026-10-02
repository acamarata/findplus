"""One owner for the in-app sign-in's state: the daemon's progress (contract §3.8).

Purpose    : The r12 review's probes P1 and P2 as permanent tests, plus the
             retry rules: a refusal the shell retries itself never shows the
             card an error; Cancel during a token exchange ends in a terminal
             phase; a slower, older exchange never paints over a newer flow;
             a live phase whose window state is gone is expired, not shown
             forever. Google is faked; the "concurrent" step runs inside the
             fake exchange, so the order is exact.
"""

from __future__ import annotations

import pytest

from findplus.providers.google_findhub import helper_state as hs
from findplus.providers.google_findhub import native_flow, native_progress
from tests.api._auth_helpers import SAME_ORIGIN_HEADERS
from tests.api._native_helpers import SHELL_HEADERS, fake_google

BASE = "/api/auth/google/native"
TOKEN = "oauth2_4/fake-value"


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


def _token(client, state):
    body = {"state": state, "oauth_token": TOKEN}
    return client.post(f"{BASE}/token", json=body, headers=SHELL_HEADERS)


def _progress(client) -> dict:
    return client.get(f"{BASE}/progress").json()


def _during_exchange(monkeypatch, action) -> None:
    """Run `action` while Google is "answering" (inside the faked exchange)."""

    def sign_in(email, token, require_email=True):
        action()
        return "kid@example.com"

    monkeypatch.setattr(native_flow, "sign_in_with_oauth_token", sign_in)


def test_begin_and_progress_carry_the_flow_id(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch)
    body = _begin(auth_client)
    assert len(body["flow"]) == 12
    assert _progress(auth_client)["flow"] == body["flow"]
    assert _begin(auth_client)["flow"] != body["flow"]


def test_a_malformed_value_keeps_the_card_waiting(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch)
    from findplus.providers.google_findhub.token_signin import InvalidInputError

    def bad(email, token, require_email=True):
        raise InvalidInputError("not that kind of value")

    monkeypatch.setattr(native_flow, "sign_in_with_oauth_token", bad)
    state = _begin(auth_client)["state"]
    assert _token(auth_client, state).status_code == 422
    assert _progress(auth_client)["phase"] == "waiting"  # the window keeps reading


def test_a_502_then_a_good_retry_ends_in_success(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch, token_error="unreachable")
    state = _begin(auth_client)["state"]
    assert _token(auth_client, state).status_code == 502
    slow = _progress(auth_client)
    assert slow["phase"] == "finishing" and "slow" in slow["message"]
    fake_google(monkeypatch)
    assert _token(auth_client, state).status_code == 200
    assert _progress(auth_client)["phase"] == "success"


def test_cancel_during_the_exchange_ends_terminal(auth_client, monkeypatch) -> None:
    """Probe P1: the person is signed in after all, so the card says so; no live phase is left."""
    fake_google(monkeypatch, needs_unlock=True)
    _during_exchange(
        monkeypatch, lambda: auth_client.post(f"{BASE}/cancel", headers=SAME_ORIGIN_HEADERS)
    )
    state = _begin(auth_client)["state"]
    assert _token(auth_client, state).status_code == 200
    done = _progress(auth_client)
    assert done["phase"] == "success" and done["unlocked"] is False
    assert done["account"] == "kid@example.com"
    assert hs.state_kind(state) is None  # never re-kinded after the cancel
    closed = {"state": state, "event": "closed"}
    assert auth_client.post(f"{BASE}/event", json=closed, headers=SHELL_HEADERS).status_code == 403
    assert _progress(auth_client)["phase"] == "success"


def test_an_old_exchange_never_paints_over_a_new_flow(auth_client, monkeypatch) -> None:
    """Probe P2: a new begin while the old window's token is being checked."""
    fake_google(monkeypatch)
    newer: dict = {}
    _during_exchange(monkeypatch, lambda: newer.update(_begin(auth_client)))
    old = _begin(auth_client)["state"]
    assert _token(auth_client, old).status_code == 200
    now = _progress(auth_client)
    assert now["phase"] == "connecting" and now["flow"] == newer["flow"]
    assert hs.state_kind(newer["state"]) == hs.KIND_NATIVE_SIGNIN


def test_an_old_failure_never_paints_over_a_new_flow(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch)
    from findplus.providers.google_findhub.token_signin import TokenRejectedError

    newer: dict = {}

    def rejected(email, token, require_email=True):
        newer.update(_begin(auth_client))
        raise TokenRejectedError("no")

    monkeypatch.setattr(native_flow, "sign_in_with_oauth_token", rejected)
    old = _begin(auth_client)["state"]
    assert _token(auth_client, old).status_code == 400
    assert _progress(auth_client)["phase"] == "connecting"


@pytest.mark.parametrize("phase", ["connecting", "waiting", "finishing"])
def test_a_live_phase_without_a_window_state_expires(auth_client, monkeypatch, phase) -> None:
    """The app quit or crashed: the state times out and the card is not left spinning."""
    fake_google(monkeypatch)
    state = _begin(auth_client)["state"]
    native_progress.set_phase(phase, "x")
    hs.drop_state(state)  # what the 10-minute TTL does
    assert _progress(auth_client)["phase"] == "idle"


def test_a_stale_unlock_wait_stays_signed_in(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch, needs_unlock=True)
    state = _begin(auth_client)["state"]
    assert _token(auth_client, state).json()["needs_unlock"] is True
    hs.drop_state(state)
    stale = _progress(auth_client)
    assert stale["phase"] == "success" and stale["unlocked"] is False


def test_a_cancel_is_seen_before_the_state_goes(auth_client, monkeypatch) -> None:
    """The shell closes on "cancelled": the expiry must never turn it into idle first."""
    fake_google(monkeypatch)
    _begin(auth_client)
    auth_client.post(f"{BASE}/cancel", headers=SAME_ORIGIN_HEADERS)
    assert _progress(auth_client)["phase"] == "cancelled"


def test_the_card_follows_a_working_window_instead_of_replacing_it(
    auth_client, monkeypatch
) -> None:
    """r12 #3: the card's begin (if_idle) must never kill a live window's state."""
    fake_google(monkeypatch)
    first = _begin(auth_client)
    body = {"mode": "signin", "if_idle": True}
    res = auth_client.post(f"{BASE}/begin", json=body, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 409 and res.json()["code"] == "window_open"
    assert res.json()["flow"] == first["flow"] and res.json()["mode"] == "signin"
    assert hs.state_kind(first["state"]) == hs.KIND_NATIVE_SIGNIN  # still alive
    assert _token(auth_client, first["state"]).status_code == 200


def test_if_idle_begins_once_the_window_is_done(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch)
    state = _begin(auth_client)["state"]
    closed = {"state": state, "event": "closed"}
    auth_client.post(f"{BASE}/event", json=closed, headers=SHELL_HEADERS)
    body = {"mode": "signin", "if_idle": True}
    res = auth_client.post(f"{BASE}/begin", json=body, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 200 and res.json()["flow"]


def test_if_idle_after_a_crash_begins_again(auth_client, monkeypatch) -> None:
    fake_google(monkeypatch)
    state = _begin(auth_client)["state"]
    hs.drop_state(state)  # the app died; the 10-minute TTL ran out
    body = {"mode": "signin", "if_idle": True}
    res = auth_client.post(f"{BASE}/begin", json=body, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 200

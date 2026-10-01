"""The helper sign-in generation: "Switch Google account" must not mistake the
OLD signed-in status for the new sign-in.

Purpose    : begin reports the current generation, a completed token exchange
             bumps it, and /api/auth/status serves it, so the dashboard can wait
             for a generation newer than the one it began with.
"""

from __future__ import annotations

import pytest

from findplus.api import _routes_auth_google_helper as helper
from findplus.providers.google_findhub import helper_state as hs
from tests.api._auth_helpers import SAME_ORIGIN_HEADERS

EXT_ORIGIN = f"chrome-extension://{hs.EXTENSION_ID}"
TOKEN_PATH = "/api/auth/google/helper/token"


@pytest.fixture(autouse=True)
def _reset():
    hs.reset_for_tests()
    yield
    hs.reset_for_tests()


def _generation(client) -> int:
    return client.get("/api/auth/status").json()["google_signin_generation"]


def test_begin_reports_the_current_generation(auth_client, no_real_browser) -> None:
    res = auth_client.post("/api/auth/google/helper/begin", headers=SAME_ORIGIN_HEADERS)
    assert res.json()["generation"] == 0
    hs.bump_signin_generation()
    res = auth_client.post("/api/auth/google/helper/begin", headers=SAME_ORIGIN_HEADERS)
    assert res.json()["generation"] == 1


def test_a_completed_helper_sign_in_bumps_the_status_generation(auth_client, monkeypatch) -> None:
    monkeypatch.setattr(helper, "sign_in_with_oauth_token", lambda *a, **k: "new@example.com")
    assert _generation(auth_client) == 0
    state = hs.create_state(hs.KIND_SIGNIN)
    auth_client.post(
        TOKEN_PATH, json={"state": state, "oauth_token": "t"}, headers={"Origin": EXT_ORIGIN}
    )
    assert _generation(auth_client) == 1


def test_a_failed_exchange_does_not_bump_the_generation(auth_client, monkeypatch) -> None:
    from findplus.providers.google_findhub.token_signin import TokenRejectedError

    def boom(*a, **k):
        raise TokenRejectedError("no")

    monkeypatch.setattr(helper, "sign_in_with_oauth_token", boom)
    state = hs.create_state(hs.KIND_SIGNIN)
    auth_client.post(
        TOKEN_PATH, json={"state": state, "oauth_token": "t"}, headers={"Origin": EXT_ORIGIN}
    )
    assert _generation(auth_client) == 0

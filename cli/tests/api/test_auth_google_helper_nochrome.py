"""No Chrome installed: the helper begin answers at once, in plain words (O16).

The Find+ helper runs in Google Chrome only. Without Chrome the daemon used to open
the system default browser, the helper never ran, and the card waited out its whole
timeout. Now begin refuses with a 409 and a reason a person can act on, and no
browser is ever started (the autouse launch guard records, never spawns).
"""

from __future__ import annotations

import pytest

from findplus.api import _routes_auth_google_helper as helper
from findplus.providers.google_findhub import helper_state as hs
from findplus.providers.google_findhub import open_signin
from findplus.providers.google_findhub.token_signin import InvalidInputError
from tests.api._auth_helpers import SAME_ORIGIN_HEADERS

EXT_ORIGIN = f"chrome-extension://{hs.EXTENSION_ID}"


@pytest.fixture(autouse=True)
def _reset():
    hs.reset_for_tests()
    yield
    hs.reset_for_tests()


@pytest.fixture
def no_chrome(monkeypatch):
    monkeypatch.setattr(open_signin, "find_google_chrome", lambda: None)


@pytest.mark.parametrize("route", ["begin", "unlock-begin"])
def test_begin_without_chrome_is_a_409_with_plain_words(
    auth_client, no_chrome, no_real_browser, route
) -> None:
    res = auth_client.post(f"/api/auth/google/helper/{route}", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "Chrome is not installed" in detail
    assert "More ways to sign in" in detail
    assert no_real_browser == []  # nothing was opened, not even the default browser
    assert not hs.has_states_of(frozenset({hs.KIND_SIGNIN, hs.KIND_UNLOCK}))


def test_begin_with_chrome_still_returns_202(auth_client, no_real_browser) -> None:
    res = auth_client.post("/api/auth/google/helper/begin", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 202
    assert res.json()["browser"] == "chrome"


def test_a_malformed_token_from_the_helper_is_a_422_not_a_502(auth_client, monkeypatch) -> None:
    def refuse(*_a, **_k):
        raise InvalidInputError("That does not look like the oauth_token value.")

    monkeypatch.setattr(helper, "sign_in_with_oauth_token", refuse)
    state = hs.create_state(hs.KIND_SIGNIN)
    res = auth_client.post(
        "/api/auth/google/helper/token",
        json={"state": state, "oauth_token": ""},
        headers={"Origin": EXT_ORIGIN},
    )
    assert res.status_code == 422
    assert res.json()["detail"] == "That does not look like the oauth_token value."
    assert hs.last_outcome()["ok"] is False

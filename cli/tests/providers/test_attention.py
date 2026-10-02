"""Lost sign-in: `attention` per provider, the deep links it allows, and every surface.

Purpose    : Google "reauth" after a revoked login, "unlock" after a key reset;
             Apple "reauth" after Apple refused the saved session; "none" for a
             provider that was never signed in. GET /api/auth/status, /api/status
             and `findplus auth --status` all say the same. Files only, no network.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from findplus.config import get_settings
from findplus.providers import attention
from findplus.providers.apple_findmy import auth as apple_auth
from tests.api._auth_helpers import SAME_ORIGIN_HEADERS


def _google_store(**data) -> None:
    path = get_settings().secrets_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _apple_store(state: int) -> None:
    path = get_settings().state_dir / "apple-account.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"login": {"state": state}}))


@pytest.mark.parametrize(
    "store,expected",
    [
        ({}, "none"),
        ({"username": "a@b.com", "aas_token": "t", "auth_revoked": "1"}, "reauth"),
        ({"username": "a@b.com", "aas_token": "t"}, "unlock"),
        ({"username": "a@b.com", "aas_token": "t", "shared_key": "k"}, "none"),
        (
            {
                "username": "a@b.com",
                "aas_token": "t",
                "shared_key": "k",
                "shared_key_account": "x@y",
            },
            "unlock",
        ),
    ],
)
def test_google_attention(tmp_db, store, expected) -> None:
    _google_store(**store)
    assert attention.attention_for(attention.GOOGLE) == expected


def test_apple_never_signed_in_needs_nothing(tmp_db) -> None:
    assert attention.attention_for(attention.APPLE) == "none"


def test_apple_refused_session_needs_reauth_until_the_next_sign_in(tmp_db) -> None:
    settings = get_settings()
    _apple_store(apple_auth.LOGGED_IN_VALUE)
    assert attention.attention_for(attention.APPLE) == "none"
    apple_auth.mark_auth_required(settings)
    assert attention.attention_for(attention.APPLE) == "reauth"
    apple_auth.clear_auth_required(settings)
    assert attention.attention_for(attention.APPLE) == "none"


def test_apple_half_finished_session_needs_reauth(tmp_db) -> None:
    _apple_store(1)
    assert attention.attention_for(attention.APPLE) == "reauth"


def test_marker_is_only_set_while_a_session_is_saved(tmp_db) -> None:
    apple_auth.mark_auth_required(get_settings())
    assert not apple_auth.auth_required_marked(get_settings())


def test_apple_locate_marks_a_refused_session(tmp_db, monkeypatch) -> None:
    from findplus.providers.apple_findmy.exceptions import AppleAuthRequiredError
    from findplus.providers.apple_findmy.provider import AppleFindMyProvider

    _apple_store(apple_auth.LOGGED_IN_VALUE)

    def refuse(self, device_id, name):
        raise AppleAuthRequiredError("Apple session expired: sign in again")

    monkeypatch.setattr(AppleFindMyProvider, "_locate", refuse)
    with pytest.raises(AppleAuthRequiredError):
        AppleFindMyProvider().locate("d", "n")
    assert attention.attention_for(attention.APPLE) == "reauth"


def test_a_broken_probe_answers_none(monkeypatch) -> None:
    monkeypatch.setattr(attention, "_google", lambda: 1 / 0)
    assert attention.attention_for(attention.GOOGLE) == "none"


def test_deep_links_open_a_login_only_while_needed(tmp_db) -> None:
    _google_store(username="a@b.com", aas_token="t", auth_revoked="1")
    assert attention.deep_link_allowed(attention.SIGNIN_GOOGLE) is True
    assert attention.deep_link_allowed(attention.UNLOCK_GOOGLE) is False
    assert attention.deep_link_allowed(attention.SIGNIN_APPLE) is False
    assert attention.deep_link_allowed("findplus://signin/evil") is False
    assert attention.deep_links({attention.GOOGLE: "unlock", attention.APPLE: "none"}) == {
        attention.SIGNIN_GOOGLE: False,
        attention.UNLOCK_GOOGLE: True,
        attention.SIGNIN_APPLE: False,
    }


def test_every_surface_says_the_same(tmp_db) -> None:
    from findplus.api import create_app
    from findplus.cli.cmd_auth import auth
    from findplus.providers.google_findhub import native_progress

    native_progress.reset()  # process-wide; another suite may have left a phase behind
    _google_store(username="a@b.com", aas_token="t", auth_revoked="1")
    client = TestClient(create_app())
    status = client.get("/api/auth/status", headers=SAME_ORIGIN_HEADERS).json()
    google = next(p for p in status["providers"] if p["id"] == attention.GOOGLE)
    assert google["attention"] == "reauth"
    assert google["deep_link"] == attention.SIGNIN_GOOGLE
    assert status["deep_links"][attention.SIGNIN_GOOGLE] is True
    assert status["google_native"]["phase"] == "idle"
    health = client.get("/api/status").json()["provider_health"]
    assert next(r for r in health if r["name"] == attention.GOOGLE)["attention"] == "reauth"
    out = CliRunner().invoke(auth, ["--status"]).output
    assert "sign in again" in out

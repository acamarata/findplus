"""Lost sign-in from the poller's own verdict (spec in-app-login.md §6, r12 #6).

Purpose    : A poll refused for its sign-in (`last_error_type` "auth", stored by
             the poller as AuthRequiredError) raises the same `attention`
             ("reauth"), deep link and tray item as the revoked mark, for the
             provider whose device was polled, and clears the moment a newer
             sign-in is saved. A provider never signed in still needs nothing.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from findplus.config import get_settings
from findplus.db.models import Device, PollRun
from findplus.db.session import session_scope
from findplus.providers import attention
from findplus.providers.apple_findmy import auth as apple_auth

NOW = datetime.now(UTC)


def _google_store(**data) -> None:
    path = get_settings().secrets_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _saved_long_ago(path) -> None:
    old = (NOW - timedelta(days=1)).timestamp()
    os.utime(path, (old, old))


def _run(provider: str, error_type: str | None, minutes_ago: int = 0) -> None:
    with session_scope() as session:
        if session.get(Device, f"{provider}-1") is None:
            session.add(
                Device(
                    device_id=f"{provider}-1",
                    name="Keys",
                    provider=provider,
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                )
            )
        session.add(
            PollRun(
                device_id=f"{provider}-1",
                started_at=NOW - timedelta(minutes=minutes_ago),
                status="auth_error" if error_type else "ok",
                error_type=error_type,
            )
        )


@pytest.mark.parametrize("error_type", ["auth", "AuthRequiredError", "unauthenticated"])
def test_a_refused_google_poll_needs_a_new_sign_in(tmp_db, error_type) -> None:
    _google_store(username="a@b.com", aas_token="t", shared_key="k")
    _saved_long_ago(get_settings().secrets_file)
    assert attention.attention_for(attention.GOOGLE) == "none"
    _run(attention.GOOGLE, error_type)
    assert attention.attention_for(attention.GOOGLE) == "reauth"
    assert attention.deep_link_allowed(attention.SIGNIN_GOOGLE) is True


def test_a_newer_sign_in_clears_it(tmp_db) -> None:
    _google_store(username="a@b.com", aas_token="t", shared_key="k")
    _run(attention.GOOGLE, "AuthRequiredError", minutes_ago=5)
    # The secrets file was written just now, after that refused poll.
    assert attention.attention_for(attention.GOOGLE) == "none"


def test_a_good_poll_after_the_refusal_clears_it(tmp_db) -> None:
    _google_store(username="a@b.com", aas_token="t", shared_key="k")
    _saved_long_ago(get_settings().secrets_file)
    _run(attention.GOOGLE, "AuthRequiredError", minutes_ago=10)
    _run(attention.GOOGLE, None, minutes_ago=1)
    assert attention.attention_for(attention.GOOGLE) == "none"


def test_other_failures_and_never_signed_in_need_nothing(tmp_db) -> None:
    _run(attention.GOOGLE, "AuthRequiredError")
    assert attention.attention_for(attention.GOOGLE) == "none"  # no account stored
    _google_store(username="a@b.com", aas_token="t", shared_key="k")
    _saved_long_ago(get_settings().secrets_file)
    _run(attention.GOOGLE, "LocationTimeoutError")
    assert attention.attention_for(attention.GOOGLE) == "none"


def test_only_the_polled_provider_is_flagged(tmp_db) -> None:
    path = get_settings().state_dir / "apple-account.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"login": {"state": apple_auth.LOGGED_IN_VALUE}}))
    _saved_long_ago(path)
    _google_store(username="a@b.com", aas_token="t", shared_key="k")
    _saved_long_ago(get_settings().secrets_file)
    _run(attention.APPLE, "AuthRequiredError")
    assert attention.attention_for(attention.APPLE) == "reauth"
    assert attention.attention_for(attention.GOOGLE) == "none"

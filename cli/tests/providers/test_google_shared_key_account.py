"""A shared key belongs to one Google account and is only trusted for that account.

Purpose    : Guards the multi-account case: a key unlocked in the Find+ Chrome
             profile while it was signed in as another account must not unlock
             this account, and must not leave a "locations unlocked" banner.
Constraints: Fake drivers, isolated state dir, no network, no real ~/.findplus.
"""

from __future__ import annotations

import json

import pytest

from findplus.providers.google_findhub import bootstrap, unlock, unlock_flow
from tests.providers._google_token_helpers import isolate_store
from tests.providers.test_google_unlock_flow import _Driver


def _write(store, data: dict) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(data))


def test_a_stored_key_is_tagged_with_the_signed_in_account(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    _write(store, {"aas_token": "x", "username": "Kid@Example.com"})
    unlock._store_shared_key("abcd")
    data = json.loads(store.read_text())
    assert data["shared_key"] == "abcd"
    assert data["shared_key_account"] == "kid@example.com"
    assert bootstrap.has_shared_key() is True


def test_a_key_tagged_to_another_account_does_not_count(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    _write(
        store,
        {
            "aas_token": "x",
            "username": "b@example.com",
            "shared_key": "abcd",
            "shared_key_account": "a@example.com",
        },
    )
    assert bootstrap.has_shared_key() is False
    assert bootstrap.needs_shared_key() is True


def test_an_untagged_legacy_key_is_still_trusted(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    _write(store, {"aas_token": "x", "username": "a@example.com", "shared_key": "abcd"})
    assert bootstrap.has_shared_key() is True


def test_a_new_key_for_a_new_account_clears_the_old_owner_key(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    _write(
        store,
        {
            "aas_token": "x",
            "username": "b@example.com",
            "owner_key": "old",
            "shared_key": "old",
            "shared_key_account": "a@example.com",
        },
    )
    unlock._store_shared_key("new")
    data = json.loads(store.read_text())
    assert not data["owner_key"]
    assert data["shared_key_account"] == "b@example.com"
    assert bootstrap.has_shared_key() is True


def test_the_flow_refuses_a_window_signed_in_as_another_account(tmp_db) -> None:
    driver = _Driver()
    driver.execute_script = lambda _s: "Google Account: Sam  (Sam@Other.com)"
    with pytest.raises(unlock_flow.AccountMismatchError) as caught:
        unlock_flow.run_shared_key_flow(
            lambda: driver, lambda: False, expected_account="kid@example.com", sleep=lambda _s: None
        )
    assert "sam@other.com" in str(caught.value)
    assert "kid@example.com" in str(caught.value)
    assert driver.quit_calls == 1


def test_the_flow_carries_on_when_the_account_cannot_be_read(tmp_db) -> None:
    driver = _Driver([json.dumps({"method": "closeView"})])
    out = unlock_flow.run_shared_key_flow(
        lambda: driver, lambda: False, expected_account="kid@example.com", sleep=lambda _s: None
    )
    assert out is None


def test_an_unreadable_account_is_reported_to_the_caller(tmp_db) -> None:
    """Fail-open stays (Google's page can change), but never silently."""
    driver = _Driver([json.dumps({"method": "closeView"})])
    seen: list[bool] = []
    unlock_flow.run_shared_key_flow(
        lambda: driver,
        lambda: False,
        expected_account="kid@example.com",
        on_unverified=lambda: seen.append(True),
        sleep=lambda _s: None,
    )
    assert seen == [True]


def test_a_verified_account_does_not_call_the_unverified_hook(tmp_db) -> None:
    driver = _Driver([json.dumps({"method": "closeView"})])
    driver.execute_script = lambda _s: "Google Account: Kid (kid@example.com)"
    seen: list[bool] = []
    unlock_flow.run_shared_key_flow(
        lambda: driver,
        lambda: False,
        expected_account="kid@example.com",
        on_unverified=lambda: seen.append(True),
        sleep=lambda _s: None,
    )
    assert seen == []

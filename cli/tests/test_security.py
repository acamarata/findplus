"""PIN hashing, session lifetime and brute-force throttling."""

from __future__ import annotations

import time

import pytest

from findplus.security import (
    LOCKOUT_SECONDS,
    MAX_ATTEMPTS,
    MIN_PIN_LENGTH,
    SessionStore,
    hash_pin,
    verify_pin,
)


# ------------------------------------------------------------------ hashing
def test_correct_pin_verifies() -> None:
    salt, digest = hash_pin("1234")
    assert verify_pin("1234", salt, digest) is True


def test_wrong_pin_rejected() -> None:
    salt, digest = hash_pin("1234")
    assert verify_pin("9999", salt, digest) is False


def test_pin_is_not_recoverable_from_what_is_stored() -> None:
    """The stored material must not contain the PIN in any readable form."""
    salt, digest = hash_pin("1234")
    assert "1234" not in salt
    assert "1234" not in digest
    assert len(digest) == 64  # 32-byte key, hex encoded


def test_same_pin_hashes_differently_each_time() -> None:
    """A per-PIN random salt defeats rainbow tables and reveals nothing by equality."""
    first_salt, first_hash = hash_pin("1234")
    second_salt, second_hash = hash_pin("1234")
    assert first_salt != second_salt
    assert first_hash != second_hash


def test_short_pins_are_refused() -> None:
    with pytest.raises(ValueError, match=f"at least {MIN_PIN_LENGTH}"):
        hash_pin("12")


def test_passphrases_are_supported() -> None:
    salt, digest = hash_pin("correct horse battery staple")
    assert verify_pin("correct horse battery staple", salt, digest) is True


def test_malformed_stored_material_does_not_crash() -> None:
    assert verify_pin("1234", "not-hex", "also-not-hex") is False


# ----------------------------------------------------------------- sessions
def test_new_session_is_valid() -> None:
    store = SessionStore()
    assert store.is_valid(store.create()) is True


def test_unknown_token_is_invalid() -> None:
    assert SessionStore().is_valid("made-up-token") is False


def test_no_token_is_invalid() -> None:
    assert SessionStore().is_valid(None) is False


def test_session_expires_after_idle_timeout() -> None:
    store = SessionStore(idle_timeout_seconds=0.2)
    token = store.create()
    time.sleep(0.3)
    assert store.is_valid(token) is False


def test_activity_refreshes_the_idle_timer() -> None:
    store = SessionStore(idle_timeout_seconds=0.4)
    token = store.create()
    for _ in range(3):
        time.sleep(0.15)
        assert store.is_valid(token) is True, "touching the session should keep it alive"


def test_zero_timeout_means_never_expire() -> None:
    store = SessionStore(idle_timeout_seconds=0)
    token = store.create()
    time.sleep(0.15)
    assert store.is_valid(token) is True


def test_revoke_invalidates_one_session() -> None:
    store = SessionStore()
    a, b = store.create(), store.create()
    store.revoke(a)
    assert store.is_valid(a) is False
    assert store.is_valid(b) is True


def test_revoke_all_signs_everyone_out() -> None:
    """Used when the PIN changes — old sessions must not survive it."""
    store = SessionStore()
    tokens = [store.create() for _ in range(3)]
    store.revoke_all()
    assert all(store.is_valid(t) is False for t in tokens)
    assert store.active_count == 0


def test_tokens_are_unguessable() -> None:
    store = SessionStore()
    tokens = {store.create() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(t) >= 32 for t in tokens)


# --------------------------------------------------------------- throttling
def test_attempts_are_allowed_up_to_the_limit() -> None:
    store = SessionStore()
    for _ in range(MAX_ATTEMPTS - 1):
        store.record_failure()
    assert store.seconds_until_retry() == 0.0
    assert store.attempts_remaining() == 1


def test_lockout_after_too_many_failures() -> None:
    """A 4-digit PIN would otherwise be brute-forced over the local API."""
    store = SessionStore()
    for _ in range(MAX_ATTEMPTS):
        store.record_failure()
    wait = store.seconds_until_retry()
    assert 0 < wait <= LOCKOUT_SECONDS
    assert store.attempts_remaining() == 0


def test_success_clears_the_failure_counter() -> None:
    store = SessionStore()
    for _ in range(MAX_ATTEMPTS):
        store.record_failure()
    store.clear_failures()
    assert store.seconds_until_retry() == 0.0
    assert store.attempts_remaining() == MAX_ATTEMPTS

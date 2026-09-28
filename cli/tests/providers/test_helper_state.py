"""The Chrome-helper state store and origin allow-list (no HTTP, no vendor)."""

from __future__ import annotations

import pytest

from findplus.providers.google_findhub import helper_state as hs


@pytest.fixture(autouse=True)
def _reset():
    hs.reset_for_tests()
    yield
    hs.reset_for_tests()


def test_a_state_is_single_use() -> None:
    state = hs.create_state(hs.KIND_SIGNIN)
    assert hs.consume_state(hs.KIND_SIGNIN, state) is True
    assert hs.consume_state(hs.KIND_SIGNIN, state) is False  # replay


def test_state_of_the_wrong_kind_is_refused() -> None:
    state = hs.create_state(hs.KIND_SIGNIN)
    assert hs.consume_state(hs.KIND_UNLOCK, state) is False
    assert hs.consume_state(hs.KIND_SIGNIN, state) is True  # still valid for its kind


def test_expired_state_is_refused(monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(hs.time, "monotonic", lambda: clock[0])
    state = hs.create_state(hs.KIND_SIGNIN)
    clock[0] += hs._STATE_TTL_SECONDS + 1
    assert hs.consume_state(hs.KIND_SIGNIN, state) is False


@pytest.mark.parametrize("bad", [None, "", "unknown-state"])
def test_missing_or_unknown_state_is_refused(bad) -> None:
    assert hs.consume_state(hs.KIND_SIGNIN, bad) is False


def test_only_the_pinned_origin_is_allowed_by_default() -> None:
    assert hs.is_allowed_extension_origin(f"chrome-extension://{hs.EXTENSION_ID}") is True
    assert hs.is_allowed_extension_origin("chrome-extension://someotherid") is False
    assert hs.is_allowed_extension_origin("http://127.0.0.1:8647") is False
    assert hs.is_allowed_extension_origin(None) is False


def test_the_store_id_is_also_allowed_once_set(monkeypatch) -> None:
    monkeypatch.setattr(hs, "CHROME_WEB_STORE_HELPER_ID", "storeidplaceholder000000000000ab")
    origins = hs.allowed_extension_origins()
    assert f"chrome-extension://{hs.EXTENSION_ID}" in origins
    assert "chrome-extension://storeidplaceholder000000000000ab" in origins
    assert hs.is_allowed_extension_origin("chrome-extension://storeidplaceholder000000000000ab")


def test_helper_seen_flag(monkeypatch) -> None:
    assert hs.helper_seen() is False
    hs.mark_seen()
    assert hs.helper_seen() is True

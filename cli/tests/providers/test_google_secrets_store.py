"""The Google token store is created as a private, valid JSON file.

v1.1.1 pre-created secrets.json EMPTY for its 0600 guarantee, and the vendored
token_cache json.load()s any file that exists, so the first token write of
every first-ever Google sign-in raised "Could not read secrets file.
Aborting." and Chrome never opened.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from findplus.providers.findhub.bootstrap import ensure_gfmt_importable as vendor_on_path
from findplus.providers.google_findhub.bootstrap import _ensure_secrets_file


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.posix_only
def test_a_new_store_is_private_valid_json(tmp_path: Path) -> None:
    store = tmp_path / "state" / "secrets.json"
    original = os.umask(0o000)
    try:
        _ensure_secrets_file(store)
    finally:
        os.umask(original)
    assert json.loads(store.read_text()) == {}
    assert _mode(store) == 0o600


def test_an_empty_store_left_by_1_1_1_is_repaired(tmp_path: Path) -> None:
    store = tmp_path / "secrets.json"
    store.touch()
    _ensure_secrets_file(store)
    assert json.loads(store.read_text()) == {}


def test_an_existing_store_keeps_its_tokens(tmp_path: Path) -> None:
    store = tmp_path / "secrets.json"
    store.write_text(json.dumps({"username": "someone@example.com"}))
    _ensure_secrets_file(store)
    assert json.loads(store.read_text()) == {"username": "someone@example.com"}


def test_the_vendored_token_cache_writes_into_a_fresh_store(tmp_path, monkeypatch) -> None:
    """The real first write, through the vendored code, on a brand-new store."""
    vendor_on_path()
    import Auth.token_cache as token_cache

    store = tmp_path / "secrets.json"
    monkeypatch.setattr(token_cache, "_get_secrets_file", lambda: str(store))
    _ensure_secrets_file(store)
    token_cache.set_cached_value("fcm_credentials", {"gcm": {"android_id": "1"}})
    assert json.loads(store.read_text())["fcm_credentials"]["gcm"]["android_id"] == "1"

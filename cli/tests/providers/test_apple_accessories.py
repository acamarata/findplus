"""Apple accessory registration: device_id derivation, round-trip, and file modes.

Every test uses tmp_path for settings.state_dir; never touches ~/.findplus.
"""

from __future__ import annotations

import base64

import pytest

from findplus.config import get_settings
from findplus.providers.apple_findmy.accessories import (
    add_accessory,
    list_accessories,
    remove_accessory,
)

KEY_28 = b"\x11" * 28


def _settings(tmp_path):
    return get_settings(state_dir=tmp_path)


def test_device_id_stability(tmp_path) -> None:
    settings = _settings(tmp_path)
    key_b64 = base64.b64encode(KEY_28).decode()
    r1 = add_accessory("Tag A", settings, private_key_b64=key_b64)
    r2 = add_accessory("Tag B", settings, private_key_b64=key_b64)
    assert r1["device_id"] == r2["device_id"]


def test_bad_base64_rejected(tmp_path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(ValueError, match="invalid base64"):
        add_accessory("Tag", settings, private_key_b64="not!valid!!")


def test_bad_key_length(tmp_path) -> None:
    settings = _settings(tmp_path)
    key_bytes = b"X" * 10
    key_b64 = base64.b64encode(key_bytes).decode()
    with pytest.raises(ValueError, match="unexpected key length"):
        add_accessory("Tag", settings, private_key_b64=key_b64)


def test_round_trip_list(tmp_path) -> None:
    settings = _settings(tmp_path)
    key_b64 = base64.b64encode(KEY_28).decode()
    record = add_accessory("Wallet Tag", settings, private_key_b64=key_b64)
    records = list_accessories(settings)
    assert len(records) == 1
    assert records[0]["device_id"] == record["device_id"]
    assert records[0]["name"] == "Wallet Tag"
    assert records[0]["kind"] == "private_key"


def test_remove(tmp_path) -> None:
    settings = _settings(tmp_path)
    key_b64 = base64.b64encode(KEY_28).decode()
    record = add_accessory("Tag", settings, private_key_b64=key_b64)
    remove_accessory(record["device_id"], settings)
    assert list_accessories(settings) == []


def test_remove_missing(tmp_path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(FileNotFoundError):
        remove_accessory("apple:0000000000000000000000", settings)


def test_file_mode_0600(tmp_path) -> None:
    settings = _settings(tmp_path)
    key_b64 = base64.b64encode(KEY_28).decode()
    record = add_accessory("Tag", settings, private_key_b64=key_b64)
    path = tmp_path / "apple" / f"{record['device_id'].replace(':', '_')}.json"
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_missing_key_material_rejected(tmp_path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(ValueError, match="plist or --private-key"):
        add_accessory("Tag", settings)


def test_list_empty(tmp_path) -> None:
    settings = _settings(tmp_path)
    assert list_accessories(settings) == []

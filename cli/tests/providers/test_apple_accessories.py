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


@pytest.mark.posix_only
def test_file_mode_0600(tmp_path) -> None:
    settings = _settings(tmp_path)
    key_b64 = base64.b64encode(KEY_28).decode()
    record = add_accessory("Tag", settings, private_key_b64=key_b64)
    path = tmp_path / "apple" / f"{record['device_id'].replace(':', '_')}.json"
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


@pytest.mark.posix_only
def test_rewrite_narrows_a_wide_mode_before_writing(tmp_path) -> None:
    """E11 review: the record is chmodded 0600 before the key payload is written,
    so a pre-existing world-readable file is never widened by a re-register."""
    settings = _settings(tmp_path)
    key_b64 = base64.b64encode(KEY_28).decode()
    record = add_accessory("Tag", settings, private_key_b64=key_b64)
    path = tmp_path / "apple" / f"{record['device_id'].replace(':', '_')}.json"
    path.chmod(0o644)
    (tmp_path / "apple").chmod(0o755)
    add_accessory("Tag renamed", settings, private_key_b64=key_b64)
    assert path.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "apple").stat().st_mode & 0o777 == 0o700


def test_missing_key_material_rejected(tmp_path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(ValueError, match="plist or --private-key"):
        add_accessory("Tag", settings)


def test_list_empty(tmp_path) -> None:
    settings = _settings(tmp_path)
    assert list_accessories(settings) == []


def test_malformed_xml_plist_rejected(tmp_path) -> None:
    """CR-C-m2: raw ExpatError used to pass through unwrapped as a 500."""
    settings = _settings(tmp_path)
    plist_path = tmp_path / "bad.plist"
    plist_path.write_bytes(b"<not-a-plist>")
    with pytest.raises(ValueError, match="not a valid property list"):
        add_accessory("Tag", settings, plist_path=plist_path)


def test_array_plist_rejected(tmp_path) -> None:
    """CR-C-m2: a top-level array has no .get(), so this used to be an
    unhandled AttributeError instead of a 422-shaped ValueError."""
    import plistlib

    settings = _settings(tmp_path)
    plist_path = tmp_path / "array.plist"
    plist_path.write_bytes(plistlib.dumps(["not", "a", "dict"]))
    with pytest.raises(ValueError, match="must be a dictionary"):
        add_accessory("Tag", settings, plist_path=plist_path)


def test_plist_key_length_is_checked(tmp_path) -> None:
    """CR-C-m3: the plist branch skipped VALID_KEY_LENGTHS entirely, so a
    3/10-byte "Private Key" plist registered."""
    import plistlib

    settings = _settings(tmp_path)
    plist_path = tmp_path / "short.plist"
    short_key_b64 = base64.b64encode(b"X" * 10).decode()
    plist_path.write_bytes(plistlib.dumps({"Private Key": short_key_b64}))
    with pytest.raises(ValueError, match="unexpected length"):
        add_accessory("Tag", settings, plist_path=plist_path)


def test_valid_plist_still_registers(tmp_path) -> None:
    """The length check must not reject a real, correctly-sized plist key."""
    import plistlib

    settings = _settings(tmp_path)
    plist_path = tmp_path / "ok.plist"
    plist_path.write_bytes(plistlib.dumps({"Private Key": base64.b64encode(KEY_28).decode()}))
    record = add_accessory("Tag", settings, plist_path=plist_path)
    assert record["kind"] == "plist"


def test_a_32_byte_key_is_rejected(tmp_path) -> None:
    """Find My keys are P-224: a 32-byte key used to register and never decrypt."""
    settings = _settings(tmp_path)
    with pytest.raises(ValueError, match="unexpected key length 32"):
        add_accessory("Tag", settings, private_key_b64=base64.b64encode(b"\x01" * 32).decode())


def test_a_findmy_pairing_plist_registers_rolling_keys(tmp_path) -> None:
    """The FindMy app's decrypted pairing record, parsed by FindMy.py itself."""
    findmy = pytest.importorskip("findmy")
    import datetime

    from tests.providers._fake_findmy import findmy_plist_bytes

    settings = _settings(tmp_path)
    plist_path = tmp_path / "airtag.plist"
    plist_path.write_bytes(findmy_plist_bytes(datetime.datetime(2026, 9, 1, 12, 0)))
    record = add_accessory("AirTag", settings, plist_path=plist_path)

    assert record["kind"] == "plist"
    accessory = findmy.FindMyAccessory.from_json(record["payload"])
    assert accessory.master_key == bytes(range(1, 29))
    assert accessory.model == "AirTag1,1"
    assert record["device_id"].startswith("apple:")
    assert list_accessories(settings)[0]["payload"] == record["payload"]


def test_an_incomplete_findmy_plist_is_a_bad_upload(tmp_path) -> None:
    pytest.importorskip("findmy")
    import plistlib

    settings = _settings(tmp_path)
    plist_path = tmp_path / "partial.plist"
    plist_path.write_bytes(plistlib.dumps({"privateKey": {"key": {"data": b"\x01" * 28}}}))
    with pytest.raises(ValueError, match="pairing plist is incomplete"):
        add_accessory("Tag", settings, plist_path=plist_path)

# Purpose: register, list and remove Apple Find My accessories (locally held keys).
# Inputs: a Find My pairing plist (rolling keys, parsed by FindMy.py's
#         FindMyAccessory.from_plist), a flat plist holding one private key, or a
#         base64 private key; findplus.config.Settings.
# Outputs: JSON records under ~/.findplus/apple/<device_id>.json (0600, dir 0700).
# Constraints: filesystem-only, no DB access; never logs plist bytes, key bytes
#              or payload; on-disk filenames sanitize ':' to '_' (Windows/NTFS
#              forbids ':' in filenames) while record["device_id"] keeps the
#              spec's "apple:<24hex>" form.
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import pathlib

#: Find My keys are P-224 scalars (findmy.KeyPair derives SECP224R1), so 28
#: bytes is the only size that can ever decrypt a report. Other lengths used to
#: register and then fail silently at every poll; they are rejected up front.
VALID_KEY_LENGTHS = {28}


def _accessories_dir(settings) -> pathlib.Path:
    d = pathlib.Path(settings.state_dir) / "apple"
    d.mkdir(mode=0o700, exist_ok=True)
    # mkdir(mode=) applies only on creation; enforce 0700 on a directory that
    # already existed with a wider mode (PRI hard rule 9).
    d.chmod(0o700)
    return d


# forge choice: sha256 of raw key bytes; stable across encoding forms.
def _derive_device_id(key_bytes: bytes) -> str:
    return "apple:" + hashlib.sha256(key_bytes).hexdigest()[:24]


def _parse_plist(path: pathlib.Path) -> tuple[str | dict, bytes]:
    import plistlib
    import xml.parsers.expat

    # plistlib.loads raises InvalidFileException for a recognized-but-broken
    # plist and lets a malformed-XML body's raw ExpatError through unwrapped
    # (CR-C-m2); both are a bad upload, not a server error, so both become
    # the same ValueError every other parse failure in this function raises.
    try:
        data = plistlib.loads(path.read_bytes())
    except (plistlib.InvalidFileException, xml.parsers.expat.ExpatError) as exc:
        raise ValueError("plist is not a valid property list") from exc
    # An array or scalar plist has no .get(): that used to be an unhandled
    # AttributeError (CR-C-m2) instead of the same "bad upload" ValueError.
    if not isinstance(data, dict):
        raise ValueError("plist must be a dictionary, not a list or scalar")
    if isinstance(data.get("privateKey"), dict):
        return _parse_findmy_plist(data)
    raw = data.get("Private Key") or data.get("privateKey")
    if not raw:
        raise ValueError("plist missing 'Private Key' or 'privateKey' field")
    try:
        key_bytes = raw if isinstance(raw, bytes) else base64.b64decode(raw)
    except Exception as exc:
        raise ValueError("plist key is neither raw bytes nor base64") from exc
    # The JSON/private_key_b64 branch below has always enforced this; the
    # plist branch skipped it, so a 3-byte "Private Key" plist registered
    # (CR-C-m3).
    if len(key_bytes) not in VALID_KEY_LENGTHS:
        raise ValueError(
            f"plist key: unexpected length {len(key_bytes)} bytes "
            f"(expected one of {sorted(VALID_KEY_LENGTHS)})"
        )
    payload = base64.b64encode(key_bytes).decode()
    return payload, key_bytes


def _parse_findmy_plist(data: dict) -> tuple[dict, bytes]:
    """A decrypted Find My pairing record (privateKey, sharedSecret, pairingDate...).

    Parsed by FindMy.py itself, so Find+ stores exactly the mapping
    FindMyAccessory.from_json() reads back. The device id hashes the master key.
    """
    import findmy

    try:
        accessory = findmy.FindMyAccessory.from_plist(data)
    except Exception as exc:
        detail = f"{type(exc).__name__} {exc}"
        raise ValueError(f"Find My pairing plist is incomplete: {detail}") from exc
    return dict(accessory.to_json()), accessory.master_key


def add_accessory(
    name: str,
    settings,
    *,
    plist_path: pathlib.Path | None = None,
    private_key_b64: str | None = None,
    allow_overwrite: bool = True,
) -> dict:
    """Register one accessory from a plist export or a raw base64 private key.

    `allow_overwrite` defaults to the CLI's long-standing silent replace, so
    `findplus apple add-accessory` behaves exactly as before. The web route
    passes False: a dashboard form has no way to say "yes, replace it", so a
    repeat submission should be reported (409), not applied.
    """
    if plist_path is not None:
        kind = "plist"
        payload, key_bytes = _parse_plist(plist_path)
    elif private_key_b64 is not None:
        kind = "private_key"
        try:
            key_bytes = base64.b64decode(private_key_b64, validate=True)
        except Exception as exc:
            # CR-C-m4: no CLI flag wording -- this reaches the dashboard too.
            raise ValueError("invalid base64") from exc
        if len(key_bytes) not in VALID_KEY_LENGTHS:
            raise ValueError(
                f"unexpected key length {len(key_bytes)} bytes "
                f"(expected one of {sorted(VALID_KEY_LENGTHS)})"
            )
        payload = private_key_b64
    else:
        raise ValueError("provide --plist or --private-key")

    device_id = _derive_device_id(key_bytes)
    record = {
        "device_id": device_id,
        "name": name,
        "kind": kind,
        "payload": payload,
        "added_at": datetime.datetime.now(tz=datetime.UTC).isoformat(),
    }
    path = _accessories_dir(settings) / f"{device_id.replace(':', '_')}.json"
    if not allow_overwrite and path.exists():
        raise FileExistsError(f"accessory {device_id!r} is already registered")
    # 0600 before the key payload is written (see save_account for the why).
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def update_accessory_payload(record: dict, payload: dict, settings) -> None:
    """Rewrite one record's payload in place (a rolling-key alignment update)."""
    path = _accessories_dir(settings) / f"{record['device_id'].replace(':', '_')}.json"
    if not path.exists():
        return
    path.chmod(0o600)
    path.write_text(json.dumps({**record, "payload": payload}, indent=2), encoding="utf-8")


def list_accessories(settings) -> list[dict]:
    """Every registered accessory, sorted by on-disk filename."""
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(_accessories_dir(settings).glob("apple_*.json"))
    ]


def remove_accessory(device_id: str, settings) -> None:
    path = _accessories_dir(settings) / f"{device_id.replace(':', '_')}.json"
    if not path.exists():
        raise FileNotFoundError(f"accessory {device_id!r} not found in {path.parent}")
    path.unlink()

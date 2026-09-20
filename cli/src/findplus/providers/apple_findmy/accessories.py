# Purpose: register, list and remove Apple Find My accessories (locally held keys).
# Inputs: a plist export or a base64 private key; findplus.config.Settings.
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

#: P-224 / P-256 / P-384 / P-521 raw scalar sizes in bytes (ceil(bits/8)). Any
#: other length is rejected immediately.
VALID_KEY_LENGTHS = {28, 32, 48, 66}


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


def _parse_plist(path: pathlib.Path) -> tuple[str, bytes]:
    import plistlib

    data = plistlib.loads(path.read_bytes())
    raw = data.get("Private Key") or data.get("privateKey")
    if not raw:
        raise ValueError("plist missing 'Private Key' or 'privateKey' field")
    key_bytes = raw if isinstance(raw, bytes) else base64.b64decode(raw)
    payload = base64.b64encode(key_bytes).decode()
    return payload, key_bytes


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
            raise ValueError("--private-key: invalid base64") from exc
        if len(key_bytes) not in VALID_KEY_LENGTHS:
            raise ValueError(
                f"--private-key: unexpected key length {len(key_bytes)} bytes "
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

"""Import-time wiring for the vendored GoogleFindMyTools.

Purpose : Put GFMT on `sys.path` and redirect its credential store to our state
          directory, WITHOUT editing any vendored cryptographic or protocol code.
Constraints:
    - Upstream resolves `secrets.json` relative to its own package directory
      (`Auth/token_cache._get_secrets_file`). We rebind that one function so the
      AAS/ADM tokens, FCM credentials and owner key land in a 0700 state dir
      outside the repository instead of inside `vendor/`.
    - This is a surgical, documented monkeypatch. It replaces a path resolver.
      It does not alter key derivation, decryption, or request signing.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from pathlib import Path

from bike_tracker.config import VENDOR_GFMT, get_settings

_lock = threading.Lock()
_ready = False


def ensure_gfmt_importable() -> Path:
    """Make GFMT importable and point its secret store at our state dir. Idempotent."""
    global _ready
    with _lock:
        if _ready:
            return VENDOR_GFMT

        if not (VENDOR_GFMT / "NovaApi").is_dir():
            raise RuntimeError(
                f"Vendored GoogleFindMyTools not found at {VENDOR_GFMT}. "
                "Run `bike-tracker doctor` for repair instructions."
            )

        if str(VENDOR_GFMT) not in sys.path:
            sys.path.insert(0, str(VENDOR_GFMT))

        settings = get_settings()
        settings.ensure_dirs()
        secrets_path = settings.secrets_file

        import Auth.token_cache as token_cache

        def _our_secrets_file() -> str:
            return str(secrets_path)

        token_cache._get_secrets_file = _our_secrets_file

        # Harden permissions on an existing store; new ones are created below.
        if secrets_path.exists():
            os.chmod(secrets_path, 0o600)

        _original_set = token_cache.set_cached_value

        def _set_and_harden(name: str, value: object) -> None:
            _original_set(name, value)
            with contextlib.suppress(OSError):
                os.chmod(secrets_path, 0o600)

        token_cache.set_cached_value = _set_and_harden

        _ready = True
        return VENDOR_GFMT


def secrets_exist() -> bool:
    return get_settings().secrets_file.exists()


def describe_stored_auth() -> dict[str, object]:
    """Report WHICH auth material is stored and where, never the values."""
    import json

    settings = get_settings()
    path = settings.secrets_file
    info: dict[str, object] = {
        "path": str(path),
        "exists": path.exists(),
        "permissions": None,
        "keys_present": [],
    }
    if not path.exists():
        return info
    info["permissions"] = oct(path.stat().st_mode & 0o777)
    try:
        data = json.loads(path.read_text())
        info["keys_present"] = sorted(data.keys())
    except (OSError, json.JSONDecodeError):
        info["keys_present"] = ["<unreadable>"]
    return info

"""Import-time wiring for the vendored GoogleFindMyTools.

Purpose : Redirect GFMT's credential store to our state directory, WITHOUT
          editing any vendored cryptographic or protocol code. Path resolution
          (sys.path, installed-wheel vs. repo dev tree) is delegated to
          findplus.providers.findhub.bootstrap — the E2 packaging resolver —
          so there is exactly one place that knows where the vendor tree lives.
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
import threading
from pathlib import Path

from findplus.config import get_settings
from findplus.providers.findhub.bootstrap import ensure_gfmt_importable as _resolve_path

_lock = threading.Lock()
_ready = False


def ensure_gfmt_importable() -> Path:
    """Make GFMT importable and point its secret store at our state dir. Idempotent."""
    global _ready
    with _lock:
        vendor_path = _resolve_path()  # raises RuntimeError if GFMT is missing
        if _ready:
            return vendor_path

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
            # Create the file 0600 BEFORE upstream writes it. Chmod-after left
            # a window in which the tokens sat on disk at the process umask,
            # which on a shared machine is long enough to copy them.
            with contextlib.suppress(OSError):
                secrets_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                secrets_path.touch(mode=0o600, exist_ok=True)
            _original_set(name, value)
            with contextlib.suppress(OSError):
                os.chmod(secrets_path, 0o600)

        token_cache.set_cached_value = _set_and_harden

        _ready = True
        return vendor_path


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


def stored_account_email() -> str | None:
    """Return the signed-in Google account email, or None.

    GoogleFindMyTools' `Auth.token_cache` persists a plain `username` key
    alongside the AAS/ADM tokens (see `Auth/username_provider.get_username`).
    This is the one value in secrets.json safe to surface (CF22, E9 review):
    an email address is an identifier, not a credential. Reads the file
    directly instead of importing the vendored `Auth.token_cache` module, so
    this never requires `ensure_gfmt_importable()` and has no import-time
    side effect on read-only status surfaces (/api/providers, `doctor`).
    """
    import json

    path = get_settings().secrets_file
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("username")
    return value or None

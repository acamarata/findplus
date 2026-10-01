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
from typing import Any

from findplus.config import get_settings
from findplus.providers.findhub.bootstrap import ensure_gfmt_importable as _resolve_path

_lock = threading.Lock()
_ready = False


def _ensure_secrets_file(path: Path) -> None:
    """Make `path` exist as a 0600 file holding at least a valid JSON object.

    Upstream token_cache json.load()s the file whenever it exists. The old
    hardening pre-created it EMPTY (touch), so the very first token write of a
    first-ever Google sign-in raised "Could not read secrets file. Aborting."
    and Chrome never opened (v1.1.1). An empty file left behind by that bug is
    repaired the same way. O_EXCL keeps the 0600 create race-free.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.stat().st_size == 0:
            path.write_text("{}", encoding="utf-8")
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("{}")
    os.chmod(path, 0o600)


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

        # Harden an existing store (0600, and repair a zero-byte file that
        # v1.1.1's empty pre-create left behind); new ones are created below.
        if secrets_path.exists():
            _ensure_secrets_file(secrets_path)

        _original_set = token_cache.set_cached_value

        def _set_and_harden(name: str, value: object) -> None:
            # Create the file 0600 BEFORE upstream writes it. Chmod-after left
            # a window in which the tokens sat on disk at the process umask,
            # which on a shared machine is long enough to copy them.
            with contextlib.suppress(OSError):
                _ensure_secrets_file(secrets_path)
            _original_set(name, value)
            with contextlib.suppress(OSError):
                os.chmod(secrets_path, 0o600)

        token_cache.set_cached_value = _set_and_harden

        install_vendor_guards()
        with contextlib.suppress(Exception):
            from .revoked import install_oauth_probe

            install_oauth_probe()

        _ready = True
        return vendor_path


def _blocked_create_driver(*_args: object, **_kwargs: object):
    """Stand-in for the vendor's browser launcher outside a user-started job.

    The real one runs `pkill -f chrome` and opens Chrome. Replaced here so an
    automatic path (a poll's decrypt) can never launch a browser or close the
    user's; only browser.py / unlock.py install a working driver, and only for
    the length of a job the user started, restoring this raiser afterwards.
    """
    from .types import BrowserLaunchBlockedError

    raise BrowserLaunchBlockedError(
        "Chrome can only be opened from a sign-in or unlock you start in Find+."
    )


def _blocked_retrieve_shared_key():
    """Stand-in for the vendor's shared-key retrieval, which calls input() and
    opens a browser. Raises the typed 'needs unlock' error instead, so a poll
    surfaces `needs: shared_key` rather than blocking on stdin or launching
    Chrome."""
    from .types import SharedKeyRequiredError

    raise SharedKeyRequiredError("This account's encrypted locations have not been unlocked yet.")


def install_vendor_guards() -> None:
    """Neutralise every vendored path that would open a browser on its own.

    Idempotent and best-effort: import failures (a stripped-down environment,
    a missing selenium) are swallowed, because a path that cannot import the
    vendored browser code cannot launch a browser either. Called at the end of
    ensure_gfmt_importable(), the one chokepoint every real vendor use passes.
    """
    set_create_driver(_blocked_create_driver)
    with contextlib.suppress(Exception):
        import KeyBackup.shared_key_retrieval as shared_key_retrieval

        shared_key_retrieval._retrieve_shared_key = _blocked_retrieve_shared_key


#: Every vendor module that did `from chrome_driver import create_driver` keeps
#: its own binding, so all of them must be rebound and restored together.
_DRIVER_MODULES = ("chrome_driver", "Auth.auth_flow", "KeyBackup.shared_key_flow")


def set_create_driver(factory: Any) -> None:
    """Point `create_driver` at `factory` on chrome_driver and every module that copied it."""
    import importlib

    for name in _DRIVER_MODULES:
        with contextlib.suppress(Exception):
            importlib.import_module(name).create_driver = factory


def restore_create_driver_guard() -> None:
    """Put the blocked create_driver back, on every module, after a job installed a real one."""
    set_create_driver(_blocked_create_driver)


def secrets_exist() -> bool:
    """True when secrets.json exists at all. NOT "signed in": see has_google_session()."""
    return get_settings().secrets_file.exists()


def _read_store() -> dict[str, object] | None:
    """secrets.json as a dict, or None when it is missing, unreadable or not an object."""
    import json

    path = get_settings().secrets_file
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def is_session_revoked() -> bool:
    """True when Google refused the saved login (revoked.py set the mark)."""
    return bool((_read_store() or {}).get("auth_revoked"))


def has_google_session() -> bool:
    """True only when the store holds a Google session: an `aas_token` AND a username.

    The one definition of "signed in to Google" (client.is_authenticated(), and
    through it /api/auth/status, doctor and the poller; describe_stored_auth()'s
    `signed_in` for `findplus start`). The file merely existing is not enough:
    FcmReceiver writes `fcm_credentials` into it before the token exchange runs,
    so a failed or cancelled sign-in left a file that used to read as "signed
    in" with no account.
    """
    data = _read_store() or {}
    if data.get("auth_revoked"):
        return False  # Google refused the saved login; see revoked.py
    return bool(data.get("aas_token")) and bool(data.get("username"))


def has_shared_key() -> bool:
    """True once the Find Hub encryption key is unlocked.

    Either the `shared_key` itself is stored, or the `owner_key` derived from it
    is already cached -- with the owner key present, decryption needs no fresh
    unlock. Either one means the "Unlock encrypted locations" step is done.
    """
    data = _read_store() or {}
    if not (data.get("shared_key") or data.get("owner_key")):
        return False
    tag = data.get("shared_key_account")
    username = str(data.get("username") or "").lower()
    # A key unlocked while another account was signed in is not this account's.
    return not (tag and username and tag != username)


def needs_shared_key() -> bool:
    """True when the account is signed in but its locations are still locked."""
    return has_google_session() and not has_shared_key()


def describe_stored_auth() -> dict[str, object]:
    """Report WHICH auth material is stored and where, never the values."""
    import json

    settings = get_settings()
    path = settings.secrets_file
    info: dict[str, object] = {
        "path": str(path),
        "exists": path.exists(),
        "signed_in": False,
        "permissions": None,
        "keys_present": [],
    }
    if not path.exists():
        return info
    info["permissions"] = oct(path.stat().st_mode & 0o777)
    info["signed_in"] = has_google_session()
    try:
        data = json.loads(path.read_text())
        info["keys_present"] = sorted(data.keys())
    except (OSError, json.JSONDecodeError, AttributeError):
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
    data = _read_store() or {}
    value = data.get("username")
    return value or None

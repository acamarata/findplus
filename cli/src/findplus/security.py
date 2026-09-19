"""App-lock: PIN hashing, sessions and brute-force throttling.

Purpose : Keep another person at this computer from casually opening the
          dashboard and reading a child's location history.
Inputs  : A user-chosen PIN or passphrase; session tokens from a cookie.
Outputs : Verification verdicts and opaque session tokens.

Constraints — read this before trusting it:
    - This is DETERRENCE, NOT ENCRYPTION. The SQLite file is still readable by
      anyone with access to this user account or the disk. The lock stops a
      person from browsing the dashboard; it does not protect the data at rest.
      Use FileVault for that.
    - The PIN is never stored. Only a salted scrypt hash is kept, in the same
      `settings` table, and it is never returned by any endpoint.
    - Verification is constant-time (`hmac.compare_digest`) and rate-limited,
      because a 4-digit PIN is otherwise trivially brute-forced over the local
      API.
    - Sessions live in memory only. Restarting the service (or rebooting) locks
      the app again, which is the desired default.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field

#: scrypt work factors. Comfortably fast for a single interactive unlock,
#: expensive enough to make offline guessing of a short PIN unpleasant.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LEN = 32
#: 128 * N * r = 32 MiB here. OpenSSL's default cap is exactly 32 MiB and rejects
#: the request, so the limit is raised explicitly rather than weakening the cost.
_SCRYPT_MAXMEM = 64 * 1024 * 1024

MIN_PIN_LENGTH = 4

#: Brute-force throttling.
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60.0


def hash_pin(pin: str) -> tuple[str, str]:
    """Return (salt_hex, hash_hex) for a PIN. The PIN itself is discarded."""
    if len(pin) < MIN_PIN_LENGTH:
        raise ValueError(f"PIN must be at least {MIN_PIN_LENGTH} characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        pin.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_LEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return salt.hex(), digest.hex()


def verify_pin(pin: str, salt_hex: str, hash_hex: str) -> bool:
    """Constant-time PIN check."""
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    digest = hashlib.scrypt(
        pin.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_LEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return hmac.compare_digest(digest, expected)


@dataclass
class _Session:
    token: str
    created_at: float
    last_seen_at: float


@dataclass
class SessionStore:
    """In-memory unlock sessions with idle expiry and attempt throttling.

    Deliberately not persisted: a service restart should re-lock the app.
    """

    idle_timeout_seconds: float = 15 * 60
    _sessions: dict[str, _Session] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _failures: list[float] = field(default_factory=list)

    # ------------------------------------------------------------- sessions
    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._sessions[token] = _Session(token=token, created_at=now, last_seen_at=now)
        return token

    def is_valid(self, token: str | None, *, touch: bool = True) -> bool:
        """True when the token is a live session. Refreshes idle time by default."""
        if not token:
            return False
        now = time.monotonic()
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return False
            if self.idle_timeout_seconds and (
                now - session.last_seen_at > self.idle_timeout_seconds
            ):
                del self._sessions[token]
                return False
            if touch:
                session.last_seen_at = now
            return True

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def revoke_all(self) -> None:
        """Used when the PIN changes or the lock is disabled."""
        with self._lock:
            self._sessions.clear()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # ------------------------------------------------------------ throttling
    def _prune_failures(self, now: float) -> None:
        cutoff = now - LOCKOUT_SECONDS
        self._failures = [t for t in self._failures if t > cutoff]

    def seconds_until_retry(self) -> float:
        """Remaining lockout, or 0 when an attempt is allowed."""
        now = time.monotonic()
        with self._lock:
            self._prune_failures(now)
            if len(self._failures) < MAX_ATTEMPTS:
                return 0.0
            return max(0.0, LOCKOUT_SECONDS - (now - self._failures[0]))

    def record_failure(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune_failures(now)
            self._failures.append(now)

    def clear_failures(self) -> None:
        with self._lock:
            self._failures.clear()

    def attempts_remaining(self) -> int:
        now = time.monotonic()
        with self._lock:
            self._prune_failures(now)
            return max(0, MAX_ATTEMPTS - len(self._failures))

"""Provider-neutral Find Hub data types.

Purpose : Decouple the rest of the app from GoogleFindMyTools' protobuf objects,
          so an upstream API change is contained to `client.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Google's Common.Status enum -> human-readable report class.
STATUS_NAMES = {
    0: "semantic",
    1: "own_report",
    2: "crowdsourced",
    3: "aggregated",
}


@dataclass(frozen=True, slots=True)
class FindHubDevice:
    """A device/tracker registered to the account."""

    device_id: str
    name: str

    def __str__(self) -> str:
        return f"{self.name} ({self.device_id})"


# RawObservation moved to findplus.providers.base (P1-E3-W3-S1-T1): it now carries a
# `provider` field so observations from any LocationProvider share one shape. Re-exported
# below so `from findplus.findhub.types import RawObservation` keeps resolving.


class FindHubError(RuntimeError):
    """Base class for all Find Hub integration failures."""


class AuthRequiredError(FindHubError):
    """No usable credentials. The user must run `findplus auth`."""


class LocationTimeoutError(FindHubError):
    """Find Hub accepted the request but no push response arrived in time."""


class DecryptionError(FindHubError):
    """The E2EE payload could not be decrypted (usually an owner-key reset)."""


class UndecryptableReportsError(FindHubError):
    """Find Hub sent location reports, but none of them could be decrypted.

    Distinct from "no new location": the poller records `decrypt_failed` so the UI
    and API say so in plain words instead of showing a healthy poll.
    """


class SharedKeyRequiredError(FindHubError):
    """The account's Find Hub end-to-end-encryption key has not been unlocked yet.

    Google encrypts Find Hub locations end to end; the key is released only to a
    browser page that has passed the account's Android screen-lock check. Until
    the user completes that once (the "Unlock encrypted locations" step), no
    tracker can be decrypted. Raised INSTEAD of letting the vendored code open a
    browser or block on stdin -- the poller turns it into a `needs: shared_key`
    state, never a crash and never a `pkill -f chrome`.
    """


class BrowserLaunchBlockedError(FindHubError):
    """A vendored path tried to launch Chrome outside a user-started Find+ job.

    The upstream `chrome_driver.create_driver` runs `pkill -f chrome` and opens
    a browser. `bootstrap.install_vendor_guards()` replaces it with a raiser so
    an automatic path (a poll's decrypt) can never do that; only browser.py /
    unlock.py install a real driver, for the length of a job the user started.
    """


from findplus.providers.base import RawObservation as RawObservation  # noqa: E402

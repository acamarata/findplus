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


from findplus.providers.base import RawObservation as RawObservation  # noqa: E402

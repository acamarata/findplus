"""Provider-neutral Find Hub data types.

Purpose : Decouple the rest of the app from GoogleFindMyTools' protobuf objects,
          so an upstream API change is contained to `client.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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


@dataclass(frozen=True, slots=True)
class RawObservation:
    """One decrypted location sighting as reported by the Find Hub network.

    `observed_at` is Google's sighting time. The retrieval time (`fetched_at`) is
    attached by the ingest layer, never by the provider.
    """

    device_id: str
    device_name: str
    latitude_e7: int
    longitude_e7: int
    observed_at: datetime
    altitude_meters: float | None = None
    accuracy_meters: float | None = None
    source: str | None = None
    is_own_report: bool | None = None
    semantic_name: str | None = None
    battery_level: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def latitude(self) -> float:
        return self.latitude_e7 / 1e7

    @property
    def longitude(self) -> float:
        return self.longitude_e7 / 1e7

    @property
    def identity(self) -> tuple[str, datetime, int, int]:
        """The deduplication key: same tuple means the same sighting."""
        return (self.device_id, self.observed_at, self.latitude_e7, self.longitude_e7)


class FindHubError(RuntimeError):
    """Base class for all Find Hub integration failures."""


class AuthRequiredError(FindHubError):
    """No usable credentials. The user must run `bike-tracker auth`."""


class LocationTimeoutError(FindHubError):
    """Find Hub accepted the request but no push response arrived in time."""


class DecryptionError(FindHubError):
    """The E2EE payload could not be decrypted (usually an owner-key reset)."""

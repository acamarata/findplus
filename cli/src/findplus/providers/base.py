# Purpose: provider abstraction protocol, shared types, and registry.
# Inputs: importlib.metadata entry-point group findplus.providers.
# Outputs: LocationProvider protocol; ProviderDevice; RawObservation; get_provider;
#          available_providers.
# Constraints: zero ORM/DB imports; Python 3.12; entry-points resolved lazily.
from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderDevice:
    """A device/tracker as reported by a provider's own device list."""

    provider: str
    device_id: str
    name: str
    kind: str | None
    raw: dict


@dataclass(frozen=True, slots=True)
class RawObservation:
    """One decrypted location sighting as reported by a provider's network.

    `observed_at` is the provider's sighting time. The retrieval time
    (`fetched_at`) is attached by the ingest layer, never by the provider.
    """

    #: Registry key of the provider that produced this observation. Keyword-only
    #: with a default so every pre-existing call site that built a RawObservation
    #: without naming a provider (google_findhub's client, test fixtures) keeps
    #: constructing successfully after this field was introduced.
    provider: str = field(default="google-find-hub", kw_only=True)
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


@runtime_checkable
class LocationProvider(Protocol):
    """What every location provider (Google Find Hub, Apple Find My, ...) exposes."""

    name: str
    display_name: str

    def is_available(self) -> tuple[bool, str]: ...
    def is_authenticated(self) -> bool: ...
    def authenticate(self, interactive: bool = True) -> str: ...
    def describe_auth(self) -> dict: ...
    def list_devices(self) -> list[ProviderDevice]: ...
    def locate(self, device_id: str, name: str) -> list[RawObservation]: ...


#: Lazy singleton cache, keyed by registry name. Populated on first get_provider() call.
_REGISTRY: dict[str, LocationProvider] = {}


def get_provider(name: str) -> LocationProvider:
    """Return the named provider, loading and caching it on first use."""
    if name in _REGISTRY:
        return _REGISTRY[name]
    for ep in importlib.metadata.entry_points(group="findplus.providers"):
        if ep.name == name:
            cls = ep.load()
            inst = cls()
            _REGISTRY[name] = inst
            return inst
    raise KeyError(f"unknown provider: {name!r}")


def available_providers() -> list[str]:
    """Names of every provider installed via the findplus.providers entry-point group."""
    return [ep.name for ep in importlib.metadata.entry_points(group="findplus.providers")]

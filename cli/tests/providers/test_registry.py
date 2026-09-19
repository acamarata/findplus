"""Provider registry: lazy entry-point resolution, never a hardcoded dict."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from findplus.providers.base import (
    LocationProvider,
    ProviderDevice,
    RawObservation,
    available_providers,
    get_provider,
)


def test_get_provider_unknown() -> None:
    with pytest.raises(KeyError):
        get_provider("nonexistent")


def test_available_providers_is_list() -> None:
    result = available_providers()
    assert isinstance(result, list)


def test_provider_device_frozen() -> None:
    device = ProviderDevice(provider="google-find-hub", device_id="d", name="n", kind=None, raw={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        device.device_id = "other"


def test_raw_observation_has_provider() -> None:
    obs = RawObservation(
        provider="google-find-hub",
        device_id="d",
        device_name="n",
        latitude_e7=410000000,
        longitude_e7=-806400000,
        observed_at=datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC),
    )
    assert obs.provider == "google-find-hub"
    assert dataclasses.fields(RawObservation)[0].name == "provider"


def test_raw_observation_provider_default() -> None:
    """Backward-compat: client.py:239 and conftest.make_observation never pass provider."""
    obs = RawObservation(
        device_id="d",
        device_name="n",
        latitude_e7=410000000,
        longitude_e7=-806400000,
        observed_at=datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC),
    )
    assert obs.provider == "google-find-hub"


def test_location_provider_protocol_check() -> None:
    class _Minimal:
        name = "fake"
        display_name = "Fake"

        def is_available(self) -> tuple[bool, str]:
            return (True, "")

        def is_authenticated(self) -> bool:
            return True

        def authenticate(self, interactive: bool = True) -> str:
            return "ok"

        def describe_auth(self) -> dict:
            return {}

        def list_devices(self) -> list[ProviderDevice]:
            return []

        def locate(self, device_id: str, name: str) -> list[RawObservation]:
            return []

    assert isinstance(_Minimal(), LocationProvider)

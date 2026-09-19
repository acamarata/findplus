# Purpose: Google Find Hub LocationProvider — wraps FindHubClient.
# Inputs: FindHubClient and bootstrap helpers from the sibling package.
# Outputs: GoogleFindHubProvider satisfying the LocationProvider protocol.
# Constraints: no direct DB access; delegates all network/crypto calls to FindHubClient.
from __future__ import annotations

from findplus.providers.base import ProviderDevice, RawObservation

from .bootstrap import ensure_gfmt_importable
from .client import FindHubClient


class GoogleFindHubProvider:
    """LocationProvider wrapper over the vendored GoogleFindMyTools client."""

    name = "google-find-hub"
    display_name = "Google Find Hub"

    def __init__(self) -> None:
        self._client = FindHubClient()

    def is_available(self) -> tuple[bool, str]:
        # No ping() on FindHubClient; the offline vendor check is the availability
        # probe (importing GoogleFindMyTools does no network I/O).
        try:
            ensure_gfmt_importable()
        except Exception as exc:
            return (False, str(exc))
        return (True, "")

    def is_authenticated(self) -> bool:
        return self._client.is_authenticated()

    def authenticate(self, interactive: bool = True) -> str:
        # FindHubClient.authenticate() takes no interactive parameter; the flag is
        # accepted here for LocationProvider conformance and ignored.
        return self._client.authenticate()

    def describe_auth(self) -> dict:
        # FindHubClient has no account_email(); return no account key.
        return {"provider": "google-find-hub"}

    def list_devices(self) -> list[ProviderDevice]:
        # FindHubDevice carries only device_id and name (no kind, no raw).
        return [
            ProviderDevice(
                provider="google-find-hub",
                device_id=d.device_id,
                name=d.name,
                kind=None,
                raw={},
            )
            for d in self._client.list_devices()
        ]

    def locate(self, device_id: str, name: str) -> list[RawObservation]:
        # RawObservation.provider defaults to "google-find-hub" (E3-T1), so every
        # observation FindHubClient builds is already tagged; no injection needed.
        return self._client.locate(device_id, name)

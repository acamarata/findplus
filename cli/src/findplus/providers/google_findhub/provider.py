# Purpose: Google Find Hub LocationProvider — wraps FindHubClient.
# Inputs: FindHubClient and bootstrap helpers from the sibling package.
# Outputs: GoogleFindHubProvider satisfying the LocationProvider protocol.
# Constraints: no direct DB access; delegates all network/crypto calls to FindHubClient.
from __future__ import annotations

from findplus.providers.base import ProviderDevice, RawObservation
from findplus.providers.findhub.bootstrap import vendor_available

from .bootstrap import stored_account_email
from .client import FindHubClient


class GoogleFindHubProvider:
    """LocationProvider wrapper over the vendored GoogleFindMyTools client."""

    name = "google-find-hub"
    display_name = "Google Find Hub"
    #: Shown by /api/providers and `findplus providers`; per-provider, not generic.
    limits = (
        "Polled on the configured interval (5 minutes or slower by default). "
        "Reports come from nearby Android devices and can be delayed or sparse."
    )

    def __init__(self) -> None:
        self._client = FindHubClient()

    def is_available(self) -> tuple[bool, str]:
        # No ping() on FindHubClient; the offline vendor check is the availability
        # probe (importing GoogleFindMyTools does no network I/O). Uses the PURE
        # probe, not ensure_gfmt_importable(): this is called by read-only status
        # surfaces (/api/providers, `findplus providers`, the poll-loop guard) and
        # must not create ~/.findplus or rebind the vendored credential store as a
        # side effect. client.py calls ensure_gfmt_importable() on every path that
        # really reaches Google, so the wiring still happens before any real use.
        try:
            return vendor_available()
        except Exception as exc:  # pragma: no cover - defensive; probe never raises
            return (False, str(exc))

    def is_authenticated(self) -> bool:
        return self._client.is_authenticated()

    def authenticate(self, interactive: bool = True) -> str:
        # FindHubClient.authenticate() takes no interactive parameter; the flag is
        # accepted here for LocationProvider conformance and ignored.
        return self._client.authenticate()

    def describe_auth(self) -> dict:
        # secrets.json's "username" key is the signed-in account email (CF22);
        # None when it is missing (never signed in, or wiped) or unreadable.
        return {"provider": "google-find-hub", "account": stored_account_email()}

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

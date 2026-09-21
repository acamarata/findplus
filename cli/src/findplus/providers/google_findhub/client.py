"""Structured client over the vendored GoogleFindMyTools.

Purpose : List Find Hub devices and retrieve decrypted location observations as
          typed Python objects.
Inputs  : A device's canonical id; credentials from the GFMT secret store.
Outputs : `FindHubDevice` / `RawObservation` values.
Constraints / why this module exists:
    - Upstream's `get_location_data_for_device()` PRINTS results and returns None
      one line at a time, dropping all but the last of a BATCH of timestamped
      reports per request. We call the same upstream crypto primitives directly
      and return every report as typed data instead.
    - No cryptographic or protocol code is modified. `retrieve_identity_key`,
      `decrypt`, `decrypt_aes_gcm` and the protobuf decoders are upstream's.
    - Two upstream robustness defects are contained here, not inherited: (1)
      `retrieve_identity_key` calls `exit(1)` on an owner-key mismatch --
      `SystemExit` is caught and re-raised as `DecryptionError`; (2)
      `location_request` busy-waits forever -- we use a `threading.Event` with
      a hard timeout.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from findplus.config import Settings, get_settings
from findplus.logging_setup import get_logger

from .bootstrap import ensure_gfmt_importable, secrets_exist
from .decrypt import decode_one_report, maybe_battery
from .types import (
    AuthRequiredError,
    DecryptionError,
    FindHubDevice,
    FindHubError,
    LocationTimeoutError,
    RawObservation,
)

log = get_logger(__name__)


class FindHubClient:
    """Thin, typed façade over GoogleFindMyTools."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._fcm_lock = threading.Lock()

    # ------------------------------------------------------------------ auth
    def is_authenticated(self) -> bool:
        return secrets_exist()

    def require_auth(self) -> None:
        if not self.is_authenticated():
            raise AuthRequiredError(
                f"No Google credentials found at {self.settings.secrets_file}. "
                "Run `findplus auth` to sign in with Chrome."
            )

    def authenticate(self) -> str:
        """Run the interactive Chrome sign-in and persist the resulting tokens.

        Returns the Google account email that was authenticated.

        This opens real Chrome at Google's own EmbeddedSetup endpoint and waits
        for the `oauth_token` cookie Google sets after a normal login (including
        whatever 2FA the account requires). Nothing here bypasses 2FA.
        """
        ensure_gfmt_importable()
        from Auth.aas_token_retrieval import get_aas_token
        from Auth.username_provider import get_username

        get_aas_token()  # value deliberately not captured, logged or returned
        email = get_username() or "<unknown>"
        log.info("auth_complete", account=email, secrets_path=str(self.settings.secrets_file))
        return email

    # --------------------------------------------------------------- devices
    def list_devices(self) -> list[FindHubDevice]:
        """Enumerate every Find Hub device/tracker visible to the account."""
        self.require_auth()
        ensure_gfmt_importable()
        from NovaApi.ListDevices.nbe_list_devices import request_device_list
        from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf

        try:
            hex_result = request_device_list()
        except SystemExit as exc:
            raise FindHubError("GoogleFindMyTools aborted during device listing") from exc
        if not hex_result:
            raise FindHubError(
                "Find Hub returned no device list. The session may have expired; "
                "try `findplus auth`."
            )

        device_list = parse_device_list_protobuf(hex_result)
        pairs = get_canonic_ids(device_list)
        devices = [FindHubDevice(device_id=cid, name=name or "(unnamed)") for name, cid in pairs]
        log.info("devices_listed", count=len(devices))
        return devices

    # -------------------------------------------------------------- locating
    def locate(self, device_id: str, device_name: str) -> list[RawObservation]:
        """Request a location update and return every decrypted report received.

        A single call commonly yields multiple sightings with distinct
        `observed_at` values — that batch is the raw material for the timeline.
        """
        self.require_auth()
        ensure_gfmt_importable()

        from Auth.fcm_receiver import FcmReceiver
        from NovaApi.ExecuteAction.LocateTracker.location_request import create_location_request
        from NovaApi.nova_request import nova_request
        from NovaApi.scopes import NOVA_ACTION_API_SCOPE
        from NovaApi.util import generate_random_uuid
        from ProtoDecoders.decoder import parse_device_update_protobuf

        request_uuid = generate_random_uuid()
        received = threading.Event()
        holder: dict[str, Any] = {}

        def _on_response(response_hex: str) -> None:
            try:
                update = parse_device_update_protobuf(response_hex)
            except Exception:
                log.warning("fcm_payload_unparseable")
                return
            if update.fcmMetadata.requestUuid == request_uuid:
                holder["update"] = update
                received.set()

        # FcmReceiver is an upstream singleton holding one long-lived push
        # connection; serialise registration so concurrent polls cannot race it.
        with self._fcm_lock:
            fcm_token = FcmReceiver().register_for_location_updates(_on_response)
            payload = create_location_request(device_id, fcm_token, request_uuid)
            response = nova_request(NOVA_ACTION_API_SCOPE, payload)

        if response is None:
            raise FindHubError(
                "Find Hub rejected the location request (Nova API returned no body). "
                "This is usually an expired session or a transient Google error."
            )

        if not received.wait(timeout=self.settings.poll_timeout_seconds):
            raise LocationTimeoutError(
                f"No Find Hub push response within {self.settings.poll_timeout_seconds:.0f}s. "
                "The tag may be out of range of any participating Android device."
            )

        return self._extract_observations(holder["update"], device_id, device_name)

    # ------------------------------------------------------------ decryption
    def _extract_observations(
        self, device_update: Any, device_id: str, device_name: str
    ) -> list[RawObservation]:
        """Decrypt a DeviceUpdate into typed observations (mirrors upstream
        `decrypt_location_response_locations()`, returning data instead of
        printing it; all crypto calls are upstream's, unchanged). Per-report
        decode/skip/build logic lives in `.decrypt` (E13 loop2 A3 split, cap
        only -- decode order and every field are unchanged)."""
        from FMDNCrypto.foreign_tracker_cryptor import decrypt
        from KeyBackup.cloud_key_decryptor import decrypt_aes_gcm
        from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import (
            is_mcu_tracker,
            retrieve_identity_key,
        )
        from ProtoDecoders import DeviceUpdate_pb2

        info = device_update.deviceMetadata.information
        registration = info.deviceRegistration

        identity_key = self._resolve_identity_key(registration, retrieve_identity_key)
        is_mcu = is_mcu_tracker(registration)
        battery = maybe_battery(info)
        reports = info.locationInformation.reports.recentLocationAndNetworkLocations
        pairs = list(zip(reports.networkLocations, reports.networkLocationTimestamps, strict=False))
        if reports.HasField("recentLocation"):
            pairs.append((reports.recentLocation, reports.recentLocationTimestamp))

        observations: list[RawObservation] = []
        for loc, ts in pairs:
            obs = decode_one_report(
                loc,
                ts,
                device_id,
                device_name,
                identity_key,
                is_mcu,
                battery,
                decrypt,
                decrypt_aes_gcm,
                DeviceUpdate_pb2,
            )
            if obs is not None:
                observations.append(obs)

        observations.sort(key=lambda o: o.observed_at)
        log.info("observations_decrypted", count=len(observations), device=device_name)
        return observations

    def _resolve_identity_key(self, registration: Any, retrieve_identity_key: Any) -> bytes:
        """The identity key lookup, with upstream's `exit(1)` turned into a typed error."""
        try:
            identity_key = retrieve_identity_key(registration)
        except SystemExit as exc:  # upstream calls exit(1) on owner-key mismatch
            raise DecryptionError(
                "Could not decrypt this tracker's identity key. This normally means "
                "the account's end-to-end-encrypted data was reset. Delete "
                f"{self.settings.secrets_file} and run `findplus auth` again."
            ) from exc
        except Exception as exc:
            raise DecryptionError(f"Identity key retrieval failed: {exc}") from exc
        if identity_key is None:
            raise DecryptionError("Identity key retrieval returned nothing.")
        return identity_key

    # ------------------------------------------------------------- utilities
    def describe(self) -> str:
        return json.dumps({"authenticated": self.is_authenticated()}, indent=2)

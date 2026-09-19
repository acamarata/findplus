"""Structured client over the vendored GoogleFindMyTools.

Purpose : List Find Hub devices and retrieve decrypted location observations as
          typed Python objects.
Inputs  : A device's canonical id; credentials from the GFMT secret store.
Outputs : `FindHubDevice` / `RawObservation` values.
Constraints / why this module exists:
    - Upstream's `get_location_data_for_device()` PRINTS results and returns None.
      The obvious shortcut (capturing stdout and regex-parsing "Latitude:" lines)
      is fragile and lossy: Google returns a BATCH of timestamped reports per
      request and a line-parser keeps only the last one. We instead call the same
      upstream crypto primitives and return every report.
    - No cryptographic or protocol code is modified. `retrieve_identity_key`,
      `decrypt`, `decrypt_aes_gcm` and the protobuf decoders are upstream's.
    - Two upstream robustness defects are contained here, not inherited:
        1. `decrypt_locations.retrieve_identity_key` calls `exit(1)` on an
           owner-key mismatch. `SystemExit` is caught and re-raised as
           `DecryptionError` so the daemon survives.
        2. `location_request` busy-waits `while result is None` forever. We use a
           `threading.Event` with a hard timeout.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any

from findplus.config import Settings, get_settings
from findplus.logging_setup import get_logger

from .bootstrap import ensure_gfmt_importable, secrets_exist
from .types import (
    STATUS_NAMES,
    AuthRequiredError,
    DecryptionError,
    FindHubDevice,
    FindHubError,
    LocationTimeoutError,
    RawObservation,
)

log = get_logger(__name__)

#: Google's Common_pb2.Status.SEMANTIC
_STATUS_SEMANTIC = 0


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
        """Decrypt a DeviceUpdate into typed observations.

        Mirrors upstream `decrypt_location_response_locations()` but returns data
        instead of printing it. All crypto calls are upstream's, unchanged.
        """
        from FMDNCrypto.foreign_tracker_cryptor import decrypt
        from KeyBackup.cloud_key_decryptor import decrypt_aes_gcm
        from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import (
            is_mcu_tracker,
            retrieve_identity_key,
        )
        from ProtoDecoders import DeviceUpdate_pb2

        info = device_update.deviceMetadata.information
        registration = info.deviceRegistration

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

        is_mcu = is_mcu_tracker(registration)
        reports = info.locationInformation.reports.recentLocationAndNetworkLocations

        pairs = list(zip(reports.networkLocations, reports.networkLocationTimestamps, strict=False))
        if reports.HasField("recentLocation"):
            pairs.append((reports.recentLocation, reports.recentLocationTimestamp))

        battery = self._maybe_battery(info)
        observations: list[RawObservation] = []

        for loc, ts in pairs:
            observed_at = datetime.fromtimestamp(int(ts.seconds), tz=UTC)
            status_name = STATUS_NAMES.get(int(loc.status), f"status_{int(loc.status)}")

            if int(loc.status) == _STATUS_SEMANTIC:
                # A named place with no coordinates. Recorded for context only:
                # it cannot be plotted, so it is not a timeline point.
                log.debug("semantic_report_skipped", name=loc.semanticLocation.locationName)
                continue

            try:
                plaintext = self._decrypt_report(
                    loc, identity_key, is_mcu, decrypt, decrypt_aes_gcm
                )
            except Exception as exc:
                log.warning("report_decrypt_failed", error=str(exc), status=status_name)
                continue

            proto_loc = DeviceUpdate_pb2.Location()
            try:
                proto_loc.ParseFromString(plaintext)
            except Exception:
                log.warning("report_proto_malformed", status=status_name)
                continue

            if not self._plausible(proto_loc.latitude, proto_loc.longitude):
                log.warning(
                    "report_coords_implausible",
                    lat_e7=proto_loc.latitude,
                    lon_e7=proto_loc.longitude,
                )
                continue

            accuracy = float(loc.geoLocation.accuracy) if loc.geoLocation.accuracy else None
            observations.append(
                RawObservation(
                    device_id=device_id,
                    device_name=device_name,
                    latitude_e7=int(proto_loc.latitude),
                    longitude_e7=int(proto_loc.longitude),
                    observed_at=observed_at,
                    altitude_meters=float(proto_loc.altitude) if proto_loc.altitude else None,
                    accuracy_meters=accuracy,
                    source=status_name,
                    is_own_report=bool(loc.geoLocation.encryptedReport.isOwnReport),
                    battery_level=battery,
                    metadata={"status_code": int(loc.status), "is_mcu": is_mcu},
                )
            )

        observations.sort(key=lambda o: o.observed_at)
        log.info("observations_decrypted", count=len(observations), device=device_name)
        return observations

    @staticmethod
    def _decrypt_report(
        loc: Any, identity_key: bytes, is_mcu: bool, decrypt: Any, decrypt_aes_gcm: Any
    ) -> bytes:
        """Dispatch to the correct upstream decryption routine for this report."""
        import hashlib

        encrypted = loc.geoLocation.encryptedReport.encryptedLocation
        public_key_random = loc.geoLocation.encryptedReport.publicKeyRandom
        if public_key_random == b"":
            # Own report: keyed by the SHA-256 of the identity key.
            return decrypt_aes_gcm(hashlib.sha256(identity_key).digest(), encrypted)
        time_offset = 0 if is_mcu else loc.geoLocation.deviceTimeOffset
        return decrypt(identity_key, encrypted, public_key_random, time_offset)

    @staticmethod
    def _maybe_battery(info: Any) -> int | None:
        """Best-effort battery read. Upstream does not expose this for all trackers."""
        for path in ("deviceComponentsInformation.batteryInfo.batteryLevel",):
            node: Any = info
            try:
                for part in path.split("."):
                    node = getattr(node, part)
                value = int(node)
            except (AttributeError, TypeError, ValueError):
                continue
            if 0 < value <= 100:
                return value
        return None

    @staticmethod
    def _plausible(lat_e7: int, lon_e7: int) -> bool:
        """Reject obviously corrupt coordinates, including the 0,0 null island."""
        if lat_e7 == 0 and lon_e7 == 0:
            return False
        return -900_000_000 <= lat_e7 <= 900_000_000 and -1_800_000_000 <= lon_e7 <= 1_800_000_000

    # ------------------------------------------------------------- utilities
    def describe(self) -> str:
        return json.dumps({"authenticated": self.is_authenticated()}, indent=2)

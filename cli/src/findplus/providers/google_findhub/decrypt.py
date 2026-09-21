"""Per-report decrypt/parse/build helpers for FindHubClient._extract_observations.

Purpose    : Turn one raw (location, timestamp) protobuf pair into a typed
             RawObservation, or None if it must be skipped. Split out of
             client.py (E13 loop2 A3) purely to keep both files under the
             300-line file / 50-line function caps; every skip reason, log
             line and field built on a RawObservation is unchanged from the
             single function this replaces.
Inputs     : The protobuf `loc`/`ts` values GoogleFindMyTools returns, the
             identity key, and the upstream crypto callables the caller
             (client.py) already resolved via its own deferred imports.
Outputs    : A `RawObservation`, or None (with a structured log line) for a
             semantic-only report, a decrypt/parse failure, or implausible
             coordinates.
Constraints: Never imports GoogleFindMyTools itself -- all upstream crypto
             is called only through the callables passed in.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from findplus.logging_setup import get_logger

from .types import STATUS_NAMES, RawObservation

log = get_logger(__name__)

#: Google's Common_pb2.Status.SEMANTIC
STATUS_SEMANTIC = 0


def plausible(lat_e7: int, lon_e7: int) -> bool:
    """Reject obviously corrupt coordinates, including the 0,0 null island."""
    if lat_e7 == 0 and lon_e7 == 0:
        return False
    return -900_000_000 <= lat_e7 <= 900_000_000 and -1_800_000_000 <= lon_e7 <= 1_800_000_000


def maybe_battery(info: Any) -> int | None:
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


def decrypt_report(
    loc: Any, identity_key: bytes, is_mcu: bool, decrypt: Any, decrypt_aes_gcm: Any
) -> bytes:
    """Dispatch to the correct upstream decryption routine for this report."""
    encrypted = loc.geoLocation.encryptedReport.encryptedLocation
    public_key_random = loc.geoLocation.encryptedReport.publicKeyRandom
    if public_key_random == b"":
        # Own report: keyed by the SHA-256 of the identity key.
        return decrypt_aes_gcm(hashlib.sha256(identity_key).digest(), encrypted)
    time_offset = 0 if is_mcu else loc.geoLocation.deviceTimeOffset
    return decrypt(identity_key, encrypted, public_key_random, time_offset)


def decrypt_and_parse(
    loc: Any,
    identity_key: bytes,
    is_mcu: bool,
    decrypt: Any,
    decrypt_aes_gcm: Any,
    device_update_pb2: Any,
    status_name: str,
) -> Any | None:
    """Decrypt + protobuf-parse one report; None (logged) on decrypt
    error, malformed protobuf, or implausible coordinates."""
    try:
        plaintext = decrypt_report(loc, identity_key, is_mcu, decrypt, decrypt_aes_gcm)
    except Exception as exc:
        log.warning("report_decrypt_failed", error=str(exc), status=status_name)
        return None

    proto_loc = device_update_pb2.Location()
    try:
        proto_loc.ParseFromString(plaintext)
    except Exception:
        log.warning("report_proto_malformed", status=status_name)
        return None

    if not plausible(proto_loc.latitude, proto_loc.longitude):
        log.warning(
            "report_coords_implausible", lat_e7=proto_loc.latitude, lon_e7=proto_loc.longitude
        )
        return None
    return proto_loc


def decode_one_report(
    loc: Any,
    ts: Any,
    device_id: str,
    device_name: str,
    identity_key: bytes,
    is_mcu: bool,
    battery: int | None,
    decrypt: Any,
    decrypt_aes_gcm: Any,
    device_update_pb2: Any,
) -> RawObservation | None:
    """One (loc, ts) pair to a `RawObservation`, or None if it must be skipped."""
    status_name = STATUS_NAMES.get(int(loc.status), f"status_{int(loc.status)}")
    if int(loc.status) == STATUS_SEMANTIC:
        # A named place with no coordinates. Recorded for context only:
        # it cannot be plotted, so it is not a timeline point.
        log.debug("semantic_report_skipped", name=loc.semanticLocation.locationName)
        return None

    proto_loc = decrypt_and_parse(
        loc, identity_key, is_mcu, decrypt, decrypt_aes_gcm, device_update_pb2, status_name
    )
    if proto_loc is None:
        return None

    accuracy = float(loc.geoLocation.accuracy) if loc.geoLocation.accuracy else None
    return RawObservation(
        device_id=device_id,
        device_name=device_name,
        latitude_e7=int(proto_loc.latitude),
        longitude_e7=int(proto_loc.longitude),
        observed_at=datetime.fromtimestamp(int(ts.seconds), tz=UTC),
        altitude_meters=float(proto_loc.altitude) if proto_loc.altitude else None,
        accuracy_meters=accuracy,
        source=status_name,
        is_own_report=bool(loc.geoLocation.encryptedReport.isOwnReport),
        battery_level=battery,
        metadata={"status_code": int(loc.status), "is_mcu": is_mcu},
    )

"""The structured decryption adapter.

These tests build REAL protobuf `Location` messages and stub only the crypto
boundary, so the parsing path exercised here is the production one. No network
calls and no Google account access occur.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from findplus.providers.google_findhub.bootstrap import ensure_gfmt_importable
from findplus.providers.google_findhub.client import FindHubClient
from findplus.providers.google_findhub.types import DecryptionError

ensure_gfmt_importable()

IDENTITY_KEY = b"\x11" * 32


def _location_bytes(lat_e7: int, lon_e7: int, altitude: int = 0) -> bytes:
    """A genuine serialized DeviceUpdate_pb2.Location, as Google would send."""
    from ProtoDecoders import DeviceUpdate_pb2

    loc = DeviceUpdate_pb2.Location()
    loc.latitude = lat_e7
    loc.longitude = lon_e7
    loc.altitude = altitude
    return loc.SerializeToString()


def _report(
    lat_e7: int,
    lon_e7: int,
    *,
    status: int = 2,
    accuracy: float = 30.0,
    own: bool = False,
    altitude: int = 0,
):
    """A stand-in for one entry in `recentLocationAndNetworkLocations`."""
    return SimpleNamespace(
        status=status,
        semanticLocation=SimpleNamespace(locationName=""),
        geoLocation=SimpleNamespace(
            accuracy=accuracy,
            deviceTimeOffset=0,
            encryptedReport=SimpleNamespace(
                encryptedLocation=_location_bytes(lat_e7, lon_e7, altitude),
                publicKeyRandom=b"" if own else b"\x02" * 16,
                isOwnReport=own,
            ),
        ),
    )


def _device_update(reports, timestamps, recent=None, recent_ts=None):
    has_recent = recent is not None
    return SimpleNamespace(
        deviceMetadata=SimpleNamespace(
            information=SimpleNamespace(
                deviceRegistration=SimpleNamespace(fastPairModelId=0),
                locationInformation=SimpleNamespace(
                    reports=SimpleNamespace(
                        recentLocationAndNetworkLocations=SimpleNamespace(
                            networkLocations=reports,
                            networkLocationTimestamps=timestamps,
                            recentLocation=recent,
                            recentLocationTimestamp=recent_ts,
                            HasField=lambda name: has_recent and name == "recentLocation",
                        )
                    )
                ),
            )
        )
    )


def _ts(unix: int):
    return SimpleNamespace(seconds=unix)


@pytest.fixture
def patched_crypto(monkeypatch: pytest.MonkeyPatch):
    """Stub the crypto boundary only; all parsing stays real."""
    import FMDNCrypto.foreign_tracker_cryptor as cryptor
    import KeyBackup.cloud_key_decryptor as decryptor
    import NovaApi.ExecuteAction.LocateTracker.decrypt_locations as dl

    monkeypatch.setattr(dl, "retrieve_identity_key", lambda _reg: IDENTITY_KEY)
    monkeypatch.setattr(dl, "is_mcu_tracker", lambda _reg: False)
    monkeypatch.setattr(decryptor, "decrypt_aes_gcm", lambda _key, blob: blob)
    monkeypatch.setattr(cryptor, "decrypt", lambda _k, blob, _r, _o: blob)
    return None


def test_single_report_is_decoded(patched_crypto) -> None:
    client = FindHubClient()
    update = _device_update([_report(411234567, -801234567)], [_ts(1789000000)])
    out = client._extract_observations(update, "TAG-001", "Moto Tag 2")

    assert len(out) == 1
    obs = out[0]
    assert obs.latitude_e7 == 411234567
    assert obs.longitude_e7 == -801234567
    assert obs.latitude == pytest.approx(41.1234567)
    assert obs.observed_at == datetime.fromtimestamp(1789000000, tz=UTC)
    assert obs.accuracy_meters == pytest.approx(30.0)
    assert obs.source == "crowdsourced"


def test_batch_of_reports_all_survive_and_are_sorted(patched_crypto) -> None:
    """This is what stdout-scraping loses: a poll returns MANY sightings."""
    client = FindHubClient()
    reports = [_report(411000000 + i * 1000, -801000000) for i in range(4)]
    stamps = [_ts(t) for t in (1789003000, 1789001000, 1789002000, 1789000000)]
    out = client._extract_observations(_device_update(reports, stamps), "TAG-001", "Moto Tag 2")

    assert len(out) == 4, "every distinct report must be returned, not just the last"
    assert [o.observed_at.timestamp() for o in out] == sorted(
        o.observed_at.timestamp() for o in out
    )


def test_recent_location_is_appended_to_the_batch(patched_crypto) -> None:
    client = FindHubClient()
    update = _device_update(
        [_report(411000000, -801000000)],
        [_ts(1789000000)],
        recent=_report(412000000, -802000000, own=True),
        recent_ts=_ts(1789005000),
    )
    out = client._extract_observations(update, "TAG-001", "Moto Tag 2")
    assert len(out) == 2
    assert out[-1].latitude_e7 == 412000000


def test_own_reports_use_the_hashed_identity_key_path(patched_crypto) -> None:
    client = FindHubClient()
    update = _device_update([_report(411000000, -801000000, own=True)], [_ts(1789000000)])
    out = client._extract_observations(update, "TAG-001", "Moto Tag 2")
    assert len(out) == 1
    assert out[0].is_own_report is True


def test_semantic_reports_are_skipped_not_plotted(patched_crypto) -> None:
    """A named place with no coordinates cannot become a map point."""
    client = FindHubClient()
    semantic = _report(0, 0, status=0)
    semantic.semanticLocation = SimpleNamespace(locationName="Home")
    update = _device_update(
        [semantic, _report(411000000, -801000000)], [_ts(1789000000), _ts(1789000100)]
    )
    out = client._extract_observations(update, "TAG-001", "Moto Tag 2")
    assert len(out) == 1
    assert out[0].source == "crowdsourced"


def test_null_island_coordinates_are_rejected(patched_crypto) -> None:
    client = FindHubClient()
    update = _device_update([_report(0, 0)], [_ts(1789000000)])
    assert client._extract_observations(update, "TAG-001", "Moto Tag 2") == []


def test_one_undecryptable_report_does_not_lose_the_batch(
    patched_crypto, monkeypatch: pytest.MonkeyPatch
) -> None:
    import FMDNCrypto.foreign_tracker_cryptor as cryptor

    calls = {"n": 0}

    def flaky(_k, blob, _r, _o):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("bad tag")
        return blob

    monkeypatch.setattr(cryptor, "decrypt", flaky)
    client = FindHubClient()
    update = _device_update(
        [_report(411000000, -801000000), _report(412000000, -802000000)],
        [_ts(1789000000), _ts(1789000100)],
    )
    out = client._extract_observations(update, "TAG-001", "Moto Tag 2")
    assert len(out) == 1, "a single bad report must not discard the good ones"


def test_upstream_exit_becomes_a_catchable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upstream calls exit(1) on an owner-key mismatch; the daemon must survive."""
    import NovaApi.ExecuteAction.LocateTracker.decrypt_locations as dl

    def boom(_reg):
        raise SystemExit(1)

    monkeypatch.setattr(dl, "retrieve_identity_key", boom)
    monkeypatch.setattr(dl, "is_mcu_tracker", lambda _reg: False)

    client = FindHubClient()
    update = _device_update([_report(411000000, -801000000)], [_ts(1789000000)])
    with pytest.raises(DecryptionError, match="end-to-end-encrypted data was reset"):
        client._extract_observations(update, "TAG-001", "Moto Tag 2")


def test_no_reports_yields_no_observations(patched_crypto) -> None:
    client = FindHubClient()
    assert client._extract_observations(_device_update([], []), "TAG-001", "Tag") == []


def test_observation_identity_is_the_dedup_key(patched_crypto) -> None:
    client = FindHubClient()
    update = _device_update([_report(411000000, -801000000)], [_ts(1789000000)])
    a = client._extract_observations(update, "TAG-001", "Moto Tag 2")[0]
    b = client._extract_observations(update, "TAG-001", "Moto Tag 2")[0]
    assert a.identity == b.identity


def test_locate_requires_authentication() -> None:
    from findplus.providers.google_findhub.types import AuthRequiredError

    client = FindHubClient()
    if client.is_authenticated():
        pytest.skip("real credentials present; the unauthenticated path cannot be exercised")
    with pytest.raises(AuthRequiredError):
        client.locate("TAG-001", "Moto Tag 2")


def test_provider_protocol() -> None:
    from findplus.providers.base import LocationProvider
    from findplus.providers.google_findhub.provider import GoogleFindHubProvider

    inst = GoogleFindHubProvider()
    assert isinstance(inst, LocationProvider)


def test_vendored_pb2_imports() -> None:
    """Every vendored protobuf module must import cleanly (no drift from the pin)."""
    import glob
    import importlib

    from findplus.config import VENDOR_GFMT

    ensure_gfmt_importable()
    pb2_files = glob.glob(str(VENDOR_GFMT / "**" / "*_pb2.py"), recursive=True)
    assert pb2_files, "expected at least one vendored _pb2.py file"
    for path in pb2_files:
        # glob.glob() and str(VENDOR_GFMT) both use os.sep, which is "\" on
        # Windows — replace both separators, not just "/", before turning the
        # relative path into a dotted module name.
        rel = path[len(str(VENDOR_GFMT)) + 1 : -3].replace("\\", "/").replace("/", ".")
        importlib.import_module(rel)

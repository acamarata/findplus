"""AppleFindMyProvider.locate(): field mapping, confidence, and error boundaries.

Never imports findmy directly; every findmy-shaped object is a local fake.
restore_account/list_accessories/_load_accessory_obj are monkeypatched at
their source modules because locate() imports them at call time.
"""

from __future__ import annotations

import collections
import datetime

import pytest

from findplus.providers import apple_findmy as apple_findmy_pkg
from findplus.providers.apple_findmy import accessories as accessories_mod
from findplus.providers.apple_findmy import auth as auth_mod
from findplus.providers.apple_findmy import provider as provider_mod
from findplus.providers.apple_findmy.exceptions import AppleAuthRequiredError
from findplus.providers.apple_findmy.provider import AppleFindMyProvider

UTC = datetime.UTC

FakeReport = collections.namedtuple(
    "FakeReport", ["latitude", "longitude", "timestamp", "confidence", "altitude", "status"]
)

_ACCESSORY = {"device_id": "apple:abc", "name": "Wallet Tag", "kind": "private_key"}


class FakeAccount:
    def __init__(self, reports) -> None:
        self._reports = reports

    def fetch_last_reports(self, acc_obj):
        return self._reports


def _patch_common(monkeypatch, reports, *, accessory=None):
    # The real is_available() checks whether `findmy` is actually importable,
    # which it is not in this dev venv; every locate() test needs the
    # available branch, so this is patched at its source module too (locate()
    # re-imports `is_available` fresh from this module on every call).
    monkeypatch.setattr(apple_findmy_pkg, "is_available", lambda: (True, ""))
    monkeypatch.setattr(auth_mod, "restore_account", lambda settings: FakeAccount(reports))
    monkeypatch.setattr(
        accessories_mod, "list_accessories", lambda settings: [accessory or _ACCESSORY]
    )
    monkeypatch.setattr(provider_mod, "_load_accessory_obj", lambda record: object())


def test_locate_maps_fields(monkeypatch) -> None:
    reports = [
        FakeReport(
            37.3318,
            -122.0312,
            datetime.datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
            "good",
            25.0,
            "located",
        ),
        FakeReport(
            37.3320,
            -122.0310,
            datetime.datetime(2026, 9, 1, 11, 0, tzinfo=UTC),
            "good",
            25.0,
            "located",
        ),
    ]
    _patch_common(monkeypatch, reports)
    provider = AppleFindMyProvider()
    results = provider.locate("apple:abc", "Wallet Tag")
    assert len(results) == 2
    assert results[0].source == "apple-find-my"
    assert results[0].device_name == "Wallet Tag"
    assert results[0].accuracy_meters == 30.0
    assert results[0].observed_at.tzinfo is not None
    assert results[0].metadata["confidence"] == "good"


def test_confidence_mapping(monkeypatch) -> None:
    reports = [
        FakeReport(1.0, 1.0, datetime.datetime(2026, 9, 1, 10, 0, tzinfo=UTC), c, None, "located")
        for c in ("excellent", "good", "medium", "poor")
    ]
    _patch_common(monkeypatch, reports)
    provider = AppleFindMyProvider()
    results = provider.locate("apple:abc", "Wallet Tag")
    expected = {"excellent": 10.0, "good": 30.0, "medium": 65.0, "poor": 150.0}
    assert len(results) == 4
    for r in results:
        assert r.accuracy_meters == expected[r.metadata["confidence"]]


def test_naive_timestamp_gets_utc(monkeypatch) -> None:
    reports = [FakeReport(1.0, 1.0, datetime.datetime(2026, 9, 1, 10, 0), "good", None, "located")]
    _patch_common(monkeypatch, reports)
    provider = AppleFindMyProvider()
    results = provider.locate("apple:abc", "Wallet Tag")
    assert results[0].observed_at.tzinfo == UTC


def test_unavailable_returns_empty(monkeypatch) -> None:
    provider = AppleFindMyProvider()
    monkeypatch.setattr(provider, "is_available", lambda: (False, "install hint"))
    assert provider.locate("apple:abc", "Wallet Tag") == []


def test_unauthenticated_propagates(monkeypatch) -> None:
    def _raise(settings):
        raise AppleAuthRequiredError("expired")

    monkeypatch.setattr(apple_findmy_pkg, "is_available", lambda: (True, ""))
    monkeypatch.setattr(auth_mod, "restore_account", _raise)
    provider = AppleFindMyProvider()
    with pytest.raises(AppleAuthRequiredError):
        provider.locate("apple:abc", "Wallet Tag")


def test_corrupt_accessory_skipped(monkeypatch) -> None:
    monkeypatch.setattr(apple_findmy_pkg, "is_available", lambda: (True, ""))
    monkeypatch.setattr(auth_mod, "restore_account", lambda settings: FakeAccount([]))
    monkeypatch.setattr(accessories_mod, "list_accessories", lambda settings: [_ACCESSORY])

    def _raise(record):
        raise ValueError("bad record")

    monkeypatch.setattr(provider_mod, "_load_accessory_obj", _raise)
    provider = AppleFindMyProvider()
    assert provider.locate("apple:abc", "Wallet Tag") == []

"""Reports that cannot be decrypted are a failure, never "no new location".

Purpose    : Google sent reports, Find+ could not read any: the client raises a
             typed error and the poller records `decrypt_failed` (not ok, red in
             the widget), instead of the healthy-looking `no_location`.
Constraints: Crypto boundary stubbed, no network, no real account.
"""

# ruff: noqa: F811  (the imported pytest fixture is re-declared as a test argument)
from __future__ import annotations

import pytest

from findplus import poller
from findplus.providers.google_findhub.client import FindHubClient
from findplus.providers.google_findhub.types import UndecryptableReportsError
from tests.providers.test_google_findhub import (
    _device_update,
    _report,
    _ts,
    patched_crypto,  # noqa: F401  (pytest fixture, imported for use)
)


def _all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    import FMDNCrypto.foreign_tracker_cryptor as cryptor

    def boom(*_a):
        raise ValueError("bad tag")

    monkeypatch.setattr(cryptor, "decrypt", boom)


def test_all_reports_failing_to_decrypt_raises_a_typed_error(
    patched_crypto, monkeypatch: pytest.MonkeyPatch
) -> None:
    _all_fail(monkeypatch)
    update = _device_update(
        [_report(411000000, -801000000), _report(412000000, -802000000)],
        [_ts(1789000000), _ts(1789000100)],
    )
    with pytest.raises(UndecryptableReportsError, match="could not decrypt"):
        FindHubClient()._extract_observations(update, "TAG-001", "Tag")


def test_semantic_only_reports_are_not_a_decrypt_failure(patched_crypto) -> None:
    from types import SimpleNamespace

    semantic = _report(0, 0, status=0)
    semantic.semanticLocation = SimpleNamespace(locationName="Home")
    update = _device_update([semantic], [_ts(1789000000)])
    assert FindHubClient()._extract_observations(update, "TAG-001", "Tag") == []


def test_the_poller_records_decrypt_failed_as_a_failure() -> None:
    class Provider:
        def locate(self, _id, _name):
            raise UndecryptableReportsError("Find Hub sent 2 location report(s) ...")

    failure, observations = poller._locate(Provider(), "TAG-001", "Tag")
    assert observations is None
    assert failure.status == "decrypt_failed"
    assert failure.error_type == "UndecryptableReportsError"
    assert failure.ok is False

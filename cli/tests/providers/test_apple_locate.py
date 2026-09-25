"""AppleFindMyProvider.locate(): real report decryption, field mapping, and errors.

The account is FakeAppleAccount (a real findmy.AsyncAppleAccount with only
fetch_raw_reports answered in memory), restored through the library's own
from_json. Reports are genuinely encrypted to the accessory's key, so the
library's fetch_location -> key generation -> decrypt path runs for real.
No socket is opened.
"""

from __future__ import annotations

import base64
import datetime

import pytest

findmy = pytest.importorskip("findmy")

from findplus.config import get_settings  # noqa: E402
from findplus.providers.apple_findmy import accessories as accessories_mod  # noqa: E402
from findplus.providers.apple_findmy import auth as auth_mod  # noqa: E402
from findplus.providers.apple_findmy.exceptions import AppleAuthRequiredError  # noqa: E402
from findplus.providers.apple_findmy.provider import AppleFindMyProvider  # noqa: E402
from findplus.providers.apple_findmy.session import AppleSession  # noqa: E402
from tests.providers._fake_findmy import (  # noqa: E402
    FakeAppleAccount,
    encrypted_report,
    findmy_plist_bytes,
)

UTC = datetime.UTC
KEY = findmy.KeyPair(bytes(range(1, 29)))


@pytest.fixture
def signed_in(tmp_path, monkeypatch):
    """A saved LOGGED_IN session; restore_account yields a FakeAppleAccount from it."""
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path))
    settings = get_settings(state_dir=tmp_path)
    account = FakeAppleAccount()
    with AppleSession(account) as session:
        session.run(account.login("a@b.com", "pw"))
    auth_mod.save_account(account, settings)
    holder: dict = {}

    def restore(s):
        holder["account"] = FakeAppleAccount.from_json(auth_mod.read_saved_state(s))
        holder["account"].reports = holder.get("reports", [])
        holder["account"].fetch_error = holder.get("fetch_error")
        return holder["account"]

    monkeypatch.setattr(auth_mod, "restore_account", restore)
    monkeypatch.setattr(AppleFindMyProvider, "is_available", lambda self: (True, ""))
    return settings, holder


def _add_key(settings) -> str:
    record = accessories_mod.add_accessory(
        "Wallet Tag", settings, private_key_b64=base64.b64encode(KEY.private_key_bytes).decode()
    )
    return record["device_id"]


def test_static_key_report_is_decrypted_and_mapped(signed_in) -> None:
    settings, holder = signed_in
    when = datetime.datetime.now(UTC).replace(microsecond=0) - datetime.timedelta(hours=1)
    holder["reports"] = [
        encrypted_report(KEY, 37.3318, -122.0312, when - datetime.timedelta(hours=1)),
        encrypted_report(KEY, 37.3320, -122.0310, when, confidence=3, accuracy=42, status=5),
    ]
    device_id = _add_key(settings)

    [obs] = AppleFindMyProvider().locate(device_id, "Wallet Tag")
    assert (obs.latitude_e7, obs.longitude_e7) == (373320000, -1220310000)
    assert obs.observed_at == when
    assert obs.observed_at.tzinfo == UTC
    assert obs.source == obs.provider == "apple-find-my"
    assert obs.accuracy_meters is None  # migration 0009: never an invented metre figure
    assert obs.altitude_meters is None
    assert obs.metadata == {"confidence": 3, "status": 5, "horizontal_accuracy": 42}


def test_rolling_key_accessory_from_a_pairing_plist(signed_in, tmp_path) -> None:
    """A real Find My pairing plist: FindMyAccessory keys roll, the report still decrypts."""
    settings, holder = signed_in
    now = datetime.datetime.now(UTC).replace(microsecond=0)
    plist = tmp_path / "tag.plist"
    plist.write_bytes(findmy_plist_bytes(now - datetime.timedelta(days=1)))
    record = accessories_mod.add_accessory("AirTag", settings, plist_path=plist)
    accessory = findmy.FindMyAccessory.from_json(record["payload"])
    current = accessory.keys_at(accessory.get_max_index(now))
    primary = next(k for k in current if k.key_type == findmy.KeyPairType.PRIMARY)
    holder["reports"] = [encrypted_report(primary, 51.5, -0.12, now)]

    [obs] = AppleFindMyProvider().locate(record["device_id"], "AirTag")
    assert (obs.latitude_e7, obs.longitude_e7) == (515000000, -1200000)
    saved = accessories_mod.list_accessories(settings)[0]["payload"]
    assert saved["alignment_date"] is not None


def test_no_report_means_no_observation(signed_in) -> None:
    settings, _holder = signed_in
    assert AppleFindMyProvider().locate(_add_key(settings), "Wallet Tag") == []


def test_unavailable_returns_empty(monkeypatch) -> None:
    provider = AppleFindMyProvider()
    monkeypatch.setattr(provider, "is_available", lambda: (False, "install hint"))
    assert provider.locate("apple:abc", "Wallet Tag") == []


def test_missing_session_propagates(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(AppleFindMyProvider, "is_available", lambda self: (True, ""))
    with pytest.raises(AppleAuthRequiredError, match="findplus auth"):
        AppleFindMyProvider().locate("apple:abc", "Wallet Tag")


@pytest.mark.parametrize(
    "error",
    [
        findmy.UnauthorizedError("Not authorized to fetch reports."),
        ValueError("No username or password specified"),
    ],
)
def test_an_expired_token_asks_for_sign_in(signed_in, error) -> None:
    """No password is saved, so a token FindMy.py cannot refresh means signing in again."""
    settings, holder = signed_in
    holder["fetch_error"] = error
    with pytest.raises(AppleAuthRequiredError, match="Apple session expired"):
        AppleFindMyProvider().locate(_add_key(settings), "Wallet Tag")


def test_corrupt_accessory_skipped(signed_in) -> None:
    settings, _holder = signed_in
    device_id = _add_key(settings)
    path = settings.state_dir / "apple" / f"{device_id.replace(':', '_')}.json"
    path.write_text(path.read_text().replace('"payload": "', '"payload": "!!'), encoding="utf-8")
    assert AppleFindMyProvider().locate(device_id, "Wallet Tag") == []


def test_is_authenticated_and_describe_auth(signed_in) -> None:
    provider = AppleFindMyProvider()
    assert provider.is_authenticated() is True
    assert provider.describe_auth() == {"provider": "apple-find-my", "account": "a@b.com"}

"""Contract: every findmy name, signature and sync/async shape Find+ relies on.

Runs against the INSTALLED findmy package (cli/pyproject.toml pins
`findmy>=0.10,<0.11`); nothing here mocks the library's surface. A findmy
release that renames, moves or re-shapes anything Find+ calls fails here
instead of at a user's first sign-in. No network: constructors only, a
from_json round trip in tmp_path, and local key material.
"""

from __future__ import annotations

import datetime
import inspect
import json
import plistlib

import pytest

findmy = pytest.importorskip("findmy")

from findplus.config import get_settings  # noqa: E402
from findplus.providers.apple_findmy import auth as auth_mod  # noqa: E402
from findplus.providers.apple_findmy.session import AppleSession  # noqa: E402
from tests.providers._fake_findmy import FakeAppleAccount, findmy_plist_bytes  # noqa: E402

Acc = findmy.AsyncAppleAccount

#: (owner, attribute, parameters Find+ passes, coroutine?)
CALLS = [
    (Acc, "login", ["username", "password"], True),
    (Acc, "get_2fa_methods", [], True),
    (Acc, "fetch_location", ["keys"], True),
    (Acc, "fetch_raw_reports", ["devices"], True),
    (Acc, "get_anisette_headers", [], True),
    (Acc, "close", [], True),
    (Acc, "td_2fa_request", [], True),
    (Acc, "td_2fa_submit", ["code"], True),
    (Acc, "sms_2fa_request", ["phone_number_id"], True),
    (Acc, "sms_2fa_submit", ["phone_number_id", "code"], True),
    (Acc, "to_json", [], False),
    (findmy.AsyncTrustedDeviceSecondFactor, "request", [], True),
    (findmy.AsyncTrustedDeviceSecondFactor, "submit", ["code"], True),
    (findmy.AsyncSmsSecondFactor, "request", [], True),
    (findmy.AsyncSmsSecondFactor, "submit", ["code"], True),
    (findmy.FindMyAccessory, "to_json", [], False),
]


def _is_async(fn) -> bool:
    """Calling it returns a coroutine (findmy's login-state decorator hides that)."""
    return inspect.iscoroutinefunction(inspect.unwrap(fn))


def _params(fn) -> list[str]:
    return [p for p in inspect.signature(fn).parameters if p not in ("self", "cls")]


@pytest.mark.parametrize(("owner", "name", "params", "is_async"), CALLS)
def test_method_exists_with_compatible_signature(owner, name, params, is_async) -> None:
    fn = getattr(owner, name)
    assert _is_async(fn) is is_async, f"{owner.__name__}.{name}"
    assert _params(fn)[: len(params)] == params


def test_top_level_names_find_plus_imports() -> None:
    """0.10 has no findmy.auth or findmy.accessory.Accessory: everything is top level."""
    for name in (
        "AsyncAppleAccount",
        "RemoteAnisetteProvider",
        "LocalAnisetteProvider",
        "LoginState",
        "FindMyAccessory",
        "KeyPair",
        "KeyPairType",
        "LocationReport",
        "AsyncTrustedDeviceSecondFactor",
        "AsyncSmsSecondFactor",
        "UnauthorizedError",
        "InvalidStateError",
        "InvalidCredentialsError",
        "UnhandledProtocolError",
    ):
        assert hasattr(findmy, name), name


def test_constructor_and_classmethod_signatures() -> None:
    assert _params(Acc.__init__)[:2] == ["anisette", "state_info"]
    assert "anisette_libs_path" in _params(Acc.from_json)
    assert _params(findmy.RemoteAnisetteProvider.__init__)[0] == "server_url"
    assert "libs_path" in _params(findmy.LocalAnisetteProvider.__init__)
    assert "name" in _params(findmy.FindMyAccessory.from_plist)
    assert _params(findmy.KeyPair.__init__)[:3] == ["private_key", "key_type", "name"]


def test_login_states_and_the_saved_value() -> None:
    assert findmy.LoginState.LOGGED_IN.value == auth_mod.LOGGED_IN_VALUE
    assert {"LOGGED_OUT", "REQUIRE_2FA", "LOGGED_IN"} <= set(findmy.LoginState.__members__)


def test_location_report_exposes_what_the_provider_reads() -> None:
    for prop in ("timestamp", "latitude", "longitude", "confidence", "status", "is_decrypted"):
        assert isinstance(inspect.getattr_static(findmy.LocationReport, prop), property), prop
    assert isinstance(
        inspect.getattr_static(findmy.LocationReport, "horizontal_accuracy"), property
    )


@pytest.mark.parametrize("remote", [True, False])
def test_account_builds_on_each_anisette_and_round_trips(tmp_path, monkeypatch, remote) -> None:
    """make_account() builds a real account on either provider, with no network,
    and a LOGGED_IN mapping saved by Find+ restores through findmy.from_json."""
    url = "http://127.0.0.1:9/anisette" if remote else None
    if url:
        monkeypatch.setenv("FINDPLUS_APPLE_ANISETTE_URL", url)
    else:
        monkeypatch.delenv("FINDPLUS_APPLE_ANISETTE_URL", raising=False)
    settings = get_settings(state_dir=tmp_path)
    account = auth_mod.make_account(settings)
    assert isinstance(account, Acc)
    assert account.login_state == findmy.LoginState.LOGGED_OUT
    kind = "aniRemote" if remote else "aniLocal"
    assert account.to_json()["anisette"]["type"] == kind

    state = account.to_json()
    state["account"].update(username="a@b.com", password="pw")
    state["login"] = {"state": findmy.LoginState.LOGGED_IN.value, "data": {"dsid": "1"}}
    with AppleSession(Acc.from_json(state)) as session:
        auth_mod.save_account(session.account, settings)
    on_disk = json.loads((tmp_path / "apple-account.json").read_text(encoding="utf-8"))
    assert on_disk["account"]["password"] is None

    restored = auth_mod.restore_account(settings)
    assert restored.login_state == findmy.LoginState.LOGGED_IN
    assert restored.to_json()["anisette"]["type"] == kind
    AppleSession(restored).close()


def test_a_restored_session_cannot_reauthenticate_without_the_password(tmp_path) -> None:
    """Pins the ValueError text provider._fetch_latest maps to AppleAuthRequiredError.

    FindMy.py re-runs its private _gsa_authenticate() on a 401; with the
    password blanked it raises before any request is made.
    """
    state = FakeAppleAccount().to_json()
    state["account"].update(username="a@b.com", password=None)
    state["login"] = {"state": findmy.LoginState.LOGGED_IN.value, "data": {}}
    session = AppleSession(Acc.from_json(state))
    with session, pytest.raises(ValueError, match="password"):
        session.run(session.account._gsa_authenticate())


def test_key_material_parses() -> None:
    key = findmy.KeyPair(bytes(range(1, 29)), name="tag")
    assert len(key.hashed_adv_key_bytes) == 32
    raw = plistlib.loads(findmy_plist_bytes(datetime.datetime(2026, 9, 1, 12, 0)))
    accessory = findmy.FindMyAccessory.from_plist(raw, name="AirTag")
    again = findmy.FindMyAccessory.from_json(json.loads(json.dumps(accessory.to_json())))
    assert again == accessory
    assert isinstance(accessory, findmy.RollingKeyPairSource)


def test_the_fake_overrides_only_real_methods_with_real_shapes() -> None:
    """FakeAppleAccount must not drift from the class it stands in for."""
    for name, fn in vars(FakeAppleAccount).items():
        if name.startswith("_") or not callable(fn):
            continue
        real = getattr(Acc, name, None)
        assert real is not None, f"fake invents {name}"
        assert _is_async(fn) is _is_async(real), name
        assert _params(fn) == _params(real), name

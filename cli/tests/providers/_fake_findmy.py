"""A fake Apple account built on FindMy.py's REAL surface, plus real key material.

Purpose    : behaviour tests drive Find+'s Apple code through the installed
             findmy package, not a duck type that could drift from it.
             FakeAppleAccount subclasses findmy.AsyncAppleAccount and overrides
             only the calls that would reach Apple (login, the 2FA request and
             submit, fetch_raw_reports, anisette headers). State transitions,
             2FA method objects, to_json/from_json, report fetching and report
             decryption all run the library's own code.
Inputs     : import only after `pytest.importorskip("findmy")`.
Outputs    : FakeAppleAccount; encrypted_report(); findmy_plist_bytes().
Constraints: no socket is ever opened: the anisette URL is loopback and never
             contacted because get_anisette_headers() is overridden.
"""

from __future__ import annotations

import datetime
import hashlib
import plistlib
import struct

import findmy
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from findmy.errors import InvalidStateError, UnhandledProtocolError

LOOPBACK_ANISETTE = "http://127.0.0.1:9/anisette"
GOOD_CODE = "123456"
SMS_NUMBER = "+1 (•••) •••-••12"
#: Apple's report timestamps count seconds from 2001-01-01 UTC.
_APPLE_EPOCH = 978307200


class FakeAppleAccount(findmy.AsyncAppleAccount):
    """AsyncAppleAccount with Apple's servers replaced by in-memory answers."""

    def __init__(self, anisette=None, *, state_info=None, requires_2fa_val=False) -> None:
        super().__init__(
            anisette or findmy.RemoteAnisetteProvider(LOOPBACK_ANISETTE), state_info=state_info
        )
        self.requires_2fa_val = requires_2fa_val
        self.trusted_device = True
        self.login_error: Exception | None = None
        self.logged_in_as: tuple[str, str] | None = None
        self.requests: list[str] = []
        self.submitted: list[str] = []
        self.reports: list[findmy.LocationReport] = []
        self.fetch_error: Exception | None = None

    async def get_anisette_headers(self, with_client_info=False, serial="0"):
        return {}

    async def login(self, username, password):
        if self.login_state != findmy.LoginState.LOGGED_OUT:
            raise InvalidStateError(f"login() in state {self.login_state}")
        if self.login_error is not None:
            raise self.login_error
        self.logged_in_as = (username, password)
        # What the real _gsa_authenticate stores, so to_json() carries it too.
        self._username, self._password = username, password
        self._account_info = {
            "account_name": username,
            "first_name": "Test",
            "last_name": "User",
            "trusted_device_2fa": self.trusted_device,
        }
        if self.requires_2fa_val:
            return self._set_login_state(
                findmy.LoginState.REQUIRE_2FA, {"adsid": "adsid", "idms_token": "idms"}
            )
        return self._logged_in()

    def _logged_in(self):
        return self._set_login_state(
            findmy.LoginState.LOGGED_IN,
            {"dsid": "1", "mobileme_data": {"tokens": {"searchPartyToken": "tok"}}},
        )

    async def get_2fa_methods(self):
        methods = []
        if self.trusted_device:
            methods.append(findmy.AsyncTrustedDeviceSecondFactor(self))
        methods.append(findmy.AsyncSmsSecondFactor(self, 7, SMS_NUMBER))
        return methods

    async def td_2fa_request(self):
        self.requests.append("trusted_device")

    async def td_2fa_submit(self, code):
        return self._check_code(code)

    async def sms_2fa_request(self, phone_number_id):
        self.requests.append(f"sms:{phone_number_id}")

    async def sms_2fa_submit(self, phone_number_id, code):
        return self._check_code(code)

    def _check_code(self, code):
        self.submitted.append(code)
        if code != GOOD_CODE:
            raise UnhandledProtocolError("SMS 2FA request failed: 401")
        return self._logged_in()

    async def fetch_raw_reports(self, devices):
        """Answer with every held report whose key the library asked about."""
        if self.fetch_error is not None:
            raise self.fetch_error
        wanted = {key for primary, secondary in devices for key in (*primary, *secondary)}
        return [r for r in self.reports if r.hashed_adv_key_b64 in wanted]


def encrypted_report(key: findmy.KeyPair, lat: float, lon: float, when, **extra) -> object:
    """A genuine encrypted report for `key`, the way a finder device builds one.

    The reverse of findmy.LocationReport.decrypt(): ECDH with an ephemeral
    P-224 key, SHA-256 KDF, AES-GCM over lat/lon/accuracy/status.
    """
    eph = ec.generate_private_key(ec.SECP224R1())
    eph_pub = eph.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    owner_pub = ec.derive_private_key(
        int.from_bytes(key.private_key_bytes, "big"), ec.SECP224R1()
    ).public_key()
    sym = hashlib.sha256(eph.exchange(ec.ECDH(), owner_pub) + b"\x00\x00\x00\x01" + eph_pub)
    sym_key = sym.digest()
    plain = struct.pack(">ii", round(lat * 1e7), round(lon * 1e7)) + bytes(
        [extra.get("accuracy", 17), extra.get("status", 0)]
    )
    enc = Cipher(algorithms.AES(sym_key[:16]), modes.GCM(sym_key[16:])).encryptor()
    body = enc.update(plain) + enc.finalize() + enc.tag
    stamp = (int(when.timestamp()) - _APPLE_EPOCH).to_bytes(4, "big")
    payload = stamp + bytes([extra.get("confidence", 2)]) + eph_pub + body
    return findmy.LocationReport(payload, key.hashed_adv_key_bytes)


def findmy_plist_bytes(paired_at: datetime.datetime) -> bytes:
    """A synthetic decrypted Find My pairing record, as FindMyAccessory.from_plist reads."""
    return plistlib.dumps(
        {
            "privateKey": {"key": {"data": b"\x00" * 57 + bytes(range(1, 29))}},
            "sharedSecret": {"key": {"data": bytes(range(32, 64))}},
            "secondarySharedSecret": {"key": {"data": bytes(range(64, 96))}},
            "pairingDate": paired_at.replace(tzinfo=None),
            "model": "AirTag1,1",
            "identifier": "00000000-0000-4000-8000-000000000001",
        }
    )

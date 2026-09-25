# Purpose: AppleFindMyProvider — the LocationProvider implementation for Apple
#          Find My, satisfying the same protocol as GoogleFindHubProvider.
# Inputs: registered accessory records (accessories.py); a saved account session
#         (auth.py); findmy.AsyncAppleAccount.fetch_location() at call time.
# Outputs: ProviderDevice rows for list_devices(); RawObservation rows for locate().
# Constraints: no findmy import at class-definition or module level (this file
#              must be importable, and the class must be instantiable, without
#              the optional `apple` extra installed — get_provider()'s entry-point
#              resolution loads and instantiates this class unconditionally).
#              A corrupt or missing accessory record never raises: locate()
#              returns [] and logs a warning instead.
from __future__ import annotations

import logging

from findplus.providers.base import ProviderDevice, RawObservation

log = logging.getLogger(__name__)


class AppleFindMyProvider:
    """LocationProvider wrapper over FindMy.py's AsyncAppleAccount + accessory registry."""

    name = "apple-find-my"
    display_name = "Apple Find My"
    #: Shown by /api/providers and `findplus providers`; per-provider, not generic.
    limits = (
        "Fetch-on-demand per accessory. Reports come from nearby Apple devices "
        "and can be delayed, sparse or unavailable."
    )

    @property
    def _settings(self):
        # Resolved per call, not frozen at construction: get_provider() keeps
        # one instance for the life of the process, and a settings object
        # captured then would keep reading the state dir that was current at
        # first use. get_settings() (not bare Settings()) so FINDPLUS_STATE_DIR
        # and test isolation resolve the same way FindHubClient's do.
        from findplus.config import get_settings

        return get_settings()

    def is_available(self) -> tuple[bool, str]:
        from findplus.providers.apple_findmy import is_available as _ia

        return _ia()

    def is_authenticated(self) -> bool:
        """True only for a saved session that finished signing in (no network)."""
        from findplus.providers.apple_findmy.auth import is_signed_in, read_saved_state

        return is_signed_in(read_saved_state(self._settings))

    def authenticate(self, interactive: bool = True) -> str:
        from .auth import sign_in_interactive

        sign_in_interactive(self._settings)
        return "ok"

    def describe_auth(self) -> dict:
        from findplus.providers.apple_findmy.auth import read_saved_state

        account = (read_saved_state(self._settings) or {}).get("account")
        username = account.get("username") if isinstance(account, dict) else None
        return {"provider": "apple-find-my", "account": username}

    def list_devices(self) -> list[ProviderDevice]:
        from .accessories import list_accessories

        return [
            ProviderDevice(
                provider="apple-find-my",
                device_id=r["device_id"],
                name=r["name"],
                kind=r["kind"],
                raw={},
            )
            for r in list_accessories(self._settings)
        ]

    def locate(self, device_id: str, name: str) -> list[RawObservation]:
        avail, _hint = self.is_available()
        if not avail:
            return []

        from findplus.providers.apple_findmy.accessories import list_accessories
        from findplus.providers.apple_findmy.auth import restore_account

        # AppleAuthRequiredError propagates uncaught, exactly like Google's
        # AuthRequiredError from findhub.types; poll_device already checked
        # is_authenticated() before calling locate() in the normal poll path.
        account = restore_account(self._settings)

        acc_record = next(
            (r for r in list_accessories(self._settings) if r["device_id"] == device_id), None
        )
        if acc_record is None:
            return []

        try:
            acc_obj = _load_accessory_obj(acc_record)
        except ValueError as exc:
            log.warning("skipping corrupt accessory %s: %s", device_id, exc)
            return []

        report = _fetch_latest(account, acc_obj, self._settings)
        _save_alignment(acc_record, acc_obj, self._settings)
        if report is None or not getattr(report, "is_decrypted", True):
            # No report in Apple's 7-day window, or one we could not decrypt:
            # never a location we would have to make up.
            return []
        return [_to_observation(report, device_id, name)]


def _fetch_latest(account, acc_obj, settings):
    """The newest decrypted report for one accessory, or None. Closes the session.

    A saved session carries no password, so when Apple's token expires
    FindMy.py cannot silently log in again: that surfaces here as
    AppleAuthRequiredError, the same as a missing session.
    """
    import findmy

    from findplus.providers.apple_findmy.auth import account_state, save_account
    from findplus.providers.apple_findmy.exceptions import AppleAuthRequiredError
    from findplus.providers.apple_findmy.session import AppleSession

    with AppleSession(account) as session:
        before = account_state(account)
        try:
            report = session.run(account.fetch_location(acc_obj))
        except (findmy.UnauthorizedError, findmy.InvalidStateError) as exc:
            raise AppleAuthRequiredError(f"Apple session expired: {exc}") from exc
        except ValueError as exc:
            if "password" not in str(exc):
                raise
            raise AppleAuthRequiredError("Apple session expired: sign in again") from exc
        if account_state(account) != before:
            save_account(account, settings)
    return report


def _save_alignment(record: dict, acc_obj, settings) -> None:
    """Keep a rolling-key accessory's key alignment, so the next fetch starts there."""
    if not isinstance(record.get("payload"), dict) or not hasattr(acc_obj, "to_json"):
        return
    from findplus.providers.apple_findmy.accessories import update_accessory_payload

    payload = acc_obj.to_json()
    if payload != record["payload"]:
        update_accessory_payload(record, payload, settings)


def _to_observation(report, device_id: str, name: str) -> RawObservation:
    """Map one decrypted findmy LocationReport onto a RawObservation row.

    `accuracy_meters` is always None. FindMy.py 0.10's LocationReport exposes
    `confidence` (an integer 1-3) and `horizontal_accuracy` (one raw byte whose
    unit neither Apple nor FindMy.py documents). An earlier revision stored an
    invented metre figure per confidence label (CF-P2-6 / R-P2-27 item 2,
    undone by migration 0009); both raw values now go to `metadata` and never
    become a number in `accuracy_meters`. See `.github/wiki/Providers.md §
    Apple Find My` for the user-facing note.
    """
    import datetime

    obs_at = report.timestamp
    if obs_at.tzinfo is None:
        obs_at = obs_at.replace(tzinfo=datetime.UTC)
    return RawObservation(
        provider="apple-find-my",
        device_id=device_id,
        device_name=name,
        latitude_e7=round(report.latitude * 1e7),
        longitude_e7=round(report.longitude * 1e7),
        observed_at=obs_at.astimezone(datetime.UTC),
        altitude_meters=None,
        accuracy_meters=None,
        source="apple-find-my",
        metadata={
            "confidence": getattr(report, "confidence", None),
            "status": getattr(report, "status", None),
            "horizontal_accuracy": getattr(report, "horizontal_accuracy", None),
        },
    )


def _load_accessory_obj(record: dict):
    """The findmy key object a record describes.

    A dict payload is a FindMy.py FindMyAccessory mapping (a Find My pairing
    plist, rolling keys); a string payload is one base64 P-224 private key
    (a static-key tag), loaded as findmy.KeyPair.
    """
    import base64

    import findmy

    payload = record.get("payload")
    try:
        if isinstance(payload, dict):
            return findmy.FindMyAccessory.from_json(payload)
        return findmy.KeyPair(base64.b64decode(payload, validate=True), name=record.get("name"))
    except Exception as exc:
        raise ValueError(f"cannot load accessory {record.get('device_id')!r}: {exc}") from exc

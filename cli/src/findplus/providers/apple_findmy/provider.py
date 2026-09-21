# Purpose: AppleFindMyProvider — the LocationProvider implementation for Apple
#          Find My, satisfying the same protocol as GoogleFindHubProvider.
# Inputs: registered accessory records (accessories.py); a saved account session
#         (auth.py); findmy.AppleAccount.fetch_last_reports() at call time.
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

#: Approximate accuracy in meters per findmy confidence label. Values are
#: forge choices, not measured — documented in wiki Providers.md § Apple Find My.
CONFIDENCE_TO_ACCURACY: dict[str, float] = {
    "excellent": 10.0,
    "good": 30.0,
    "medium": 65.0,
    "poor": 150.0,
}


class AppleFindMyProvider:
    """LocationProvider wrapper over FindMy.py's AppleAccount + accessory registry."""

    name = "apple-find-my"
    display_name = "Apple Find My"
    #: Shown by /api/providers and `findplus providers`; per-provider, not generic.
    limits = (
        "Fetch-on-demand per accessory. Reports come from nearby Apple devices "
        "and can be delayed, sparse or unavailable."
    )

    def __init__(self) -> None:
        # get_settings() (not bare Settings()) so FINDPLUS_STATE_DIR / test
        # isolation resolve the same way GoogleFindHubProvider's FindHubClient
        # does; get_provider()'s cls() call requires zero constructor args.
        from findplus.config import get_settings

        self._settings = get_settings()

    def is_available(self) -> tuple[bool, str]:
        from findplus.providers.apple_findmy import is_available as _ia

        return _ia()

    def is_authenticated(self) -> bool:
        from findplus.providers.apple_findmy.auth import _state_path

        return _state_path(self._settings).exists()

    def authenticate(self, interactive: bool = True) -> str:
        from .auth import sign_in_interactive

        sign_in_interactive(self._settings)
        return "ok"

    def describe_auth(self) -> dict:
        return {"provider": "apple-find-my"}

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
        # AuthRequiredError from findhub.types — poll_device already checked
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

        return [_to_observation(r, device_id, name) for r in account.fetch_last_reports(acc_obj)]


def _to_observation(report, device_id: str, name: str) -> RawObservation:
    """Map one findmy Report onto a RawObservation row.

    Every Report attribute is read with getattr and a default: the installed
    FindMy.py version may not expose all of them.
    """
    import datetime

    obs_at = report.timestamp
    if obs_at.tzinfo is None:
        obs_at = obs_at.replace(tzinfo=datetime.UTC)
    confidence = getattr(report, "confidence", None)
    return RawObservation(
        provider="apple-find-my",
        device_id=device_id,
        device_name=name,
        latitude_e7=round(report.latitude * 1e7),
        longitude_e7=round(report.longitude * 1e7),
        observed_at=obs_at,
        altitude_meters=getattr(report, "altitude", None),
        accuracy_meters=None,
        source="apple-find-my",
        metadata={
            "confidence": confidence,
            "status": getattr(report, "status", None),
        },
    )


def _load_accessory_obj(record: dict):
    import findmy.accessory

    try:
        return findmy.accessory.Accessory.from_dict(record)
    except Exception as exc:
        raise ValueError(f"cannot load accessory {record.get('device_id')!r}: {exc}") from exc

"""The P2 additions to the GET/PATCH /api/settings body.

Purpose    : Build the one pinned settings body and persist the two
             config.env-backed fields, kept beside routes_settings.py
             rather than inside it so that file stays under the 300-line
             cap (PRI rule 7), the same way _widget.py already is.
Inputs     : An open DB session; the PATCH body's poll/retention values.
Outputs    : The settings dict; writes to ~/.findplus/config.env.
Constraints: _write_config_fields raises ValueError only, so the route can
             turn it into the 422 the spec pins for these two fields.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from findplus.appsettings import load_settings
from findplus.config import get_settings, validate_config_key, write_config_key
from findplus.state import get_setting, set_setting

#: The wire key whose explicit null means "keep history forever".
_RETENTION_KEY = "history.retention_days"

#: The eight onboarding step ids the wizard walks, in order. The only values
#: `onboarding.last_step` accepts, so a stale client cannot wedge a future
#: session on a step that does not exist (specs/onboarding.md § 2).
_ONBOARDING_STEPS = (
    "welcome",
    "signin",
    "devices",
    "groups",
    "places",
    "notifications",
    "applock",
    "done",
)

#: The two onboarding wire keys, dotted like every other P2 field (ruling F6).
_COMPLETED_KEY = "onboarding.completed_at"
_LAST_STEP_KEY = "onboarding.last_step"


def validate_step(value: str | None) -> None:
    """Raise ValueError unless `value` is one of the eight step ids, or None.

    None clears the resume point. `findplus setup --yes` writes "headless"
    straight to the settings table (R-P2-24) and never comes through here, so
    that value is deliberately not accepted over HTTP.
    """
    if value is not None and value not in _ONBOARDING_STEPS:
        raise ValueError(f"Unknown onboarding step {value!r}.")


async def _raw_patch_body(request: Request) -> dict[str, Any]:
    """The decoded request body, so the route can tell null from omitted.

    FastAPI maps an explicit JSON `null` on an embedded Body field to that
    field's declared default, exactly as it maps a missing key, so no sentinel
    default can separate `{"history.retention_days": null}` (keep forever) from
    a PATCH that never mentioned retention (leave it alone). Starlette caches
    the body bytes, so reading it a second time here costs one re-parse and
    does not consume the stream FastAPI already read.
    """
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _settings_body(session) -> dict[str, Any]:
    """The one pinned GET/PATCH /api/settings body (service-and-settings.md § 4).

    Built here rather than in AppSettings.public() because two of the three new
    fields live in config.env, not the settings table.
    """
    settings = get_settings()
    return {
        **load_settings(session).public(),
        "poll.interval_minutes": round(settings.poll_interval_minutes),
        "history.retention_days": None if settings.retention_days == 0 else settings.retention_days,
        "alerts.native_detail": get_setting(session, "alerts.native_detail", "0") == "1",
        # Appended after public(), never merged into the AppSettings dataclass,
        # so the PIN hash and salt public() already drops cannot reappear here.
        "onboarding.completed_at": get_setting(session, "onboarding.completed_at"),
        "onboarding.last_step": get_setting(session, "onboarding.last_step"),
    }


def _write_onboarding_fields(
    session, raw_body: dict[str, Any], completed_at: str | None, last_step: str | None
) -> None:
    """Persist whichever of the two onboarding keys the PATCH body named.

    Presence in `raw_body` is the signal, never a sentinel default: FastAPI maps
    an explicit wire `null` onto an embedded field's declared default exactly as
    it maps an absent key, and `null` is meaningful for both of these (it clears
    the value). Same mechanism `retention_sent` already uses below.

    Raises ValueError on an unknown step id, which the caller turns into the 422
    specs/onboarding.md § 2 pins.
    """
    if _COMPLETED_KEY in raw_body:
        set_setting(session, _COMPLETED_KEY, completed_at)
    if _LAST_STEP_KEY in raw_body:
        validate_step(last_step)
        set_setting(session, _LAST_STEP_KEY, last_step)


def _write_config_fields(
    poll_interval_minutes: int | None, retention_days: int | None, retention_sent: bool
) -> None:
    """Validate and persist the two config.env-backed PATCH fields.

    `retention_sent` says whether the caller named the key at all; with it sent
    and None, retention is turned off by storing 0, which config.py already
    reads as "keep forever".

    Raises ValueError, which the caller turns into a 422 -- the spec pins 422
    for these two, while theme/idle_minutes/lock_enabled keep their 400.
    """
    if poll_interval_minutes is not None:
        validate_config_key("poll_interval_minutes", str(poll_interval_minutes))
    if retention_sent and retention_days is not None:
        validate_config_key("retention_days", str(retention_days))
    # Both fields are checked before either is written, so a request carrying
    # one good and one bad value changes nothing at all.
    if poll_interval_minutes is not None:
        write_config_key(get_settings(), "POLL_INTERVAL_MINUTES", str(poll_interval_minutes))
    if retention_sent:
        write_config_key(
            get_settings(), "RETENTION_DAYS", "0" if retention_days is None else str(retention_days)
        )

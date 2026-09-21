"""Per-key settings sub-routes: app.start_at_login, widget.show_map, onboarding.

Purpose    : The dotted-key GET/POST pairs R-P2-6/F6 pinned for every field
             the dashboard writes one at a time. Split out of routes_settings
             at the E13 loop-1 function/file-cap refactor; every route is
             byte-identical in path, method and payload.
Inputs     : Single `{value: ...}` JSON bodies.
Outputs    : `{"<dotted.key>": value}` echo payloads.
Constraints: These handlers close over nothing, so they are module-level
             functions registered by register_key_routes(). The LaunchAgent
             toggle runs findplus.service in-process, never a subprocess.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from findplus.config import get_settings
from findplus.db.session import session_scope
from findplus.logging_setup import get_logger
from findplus.state import get_setting, set_setting

from ._settings_fields import validate_step
from ._widget import _widget_show_map

log = get_logger(__name__)

# The desktop app installs into /Applications; --program overrides
# ProgramArguments[0] so the LaunchAgent points at the bundled sidecar
# rather than a venv findplus (specs/desktop-app.md § Start at login).
_APP_PROGRAM = "/Applications/Find+.app/Contents/MacOS/findplus-daemon"


def get_start_at_login() -> dict[str, Any]:
    with session_scope() as session:
        value = get_setting(session, "app.start_at_login", "0")
    return {"app.start_at_login": value == "1"}


def set_start_at_login(value: bool = Body(..., embed=True)) -> dict[str, Any]:
    """Toggle the desktop app's LaunchAgent through findplus.service.

    api-contract.md pins this as "toggles the LaunchAgent RunAtLoad flag
    for com.acamarata.findplus via `findplus.service`". It used to shell
    out to `findplus-daemon` instead, which is the sidecar binary inside
    Find+.app and is not on any PATH -- including the sidecar's own, since
    this code RUNS in that process. Toggling the switch in the dashboard
    raised OSError and returned 500, every time, on every platform.
    Calling the facade in-process is the same one implementation the CLI
    uses (service.runtime.install/uninstall), minus the PATH dependency.
    """
    from findplus.service import runtime

    with session_scope() as session:
        set_setting(session, "app.start_at_login", "1" if value else "0")

    try:
        if value:
            runtime.install(confirmed=True, program=_APP_PROGRAM)
        else:
            runtime.uninstall()
    except Exception as exc:  # a launchctl/systemd failure is not a crash
        log.error("start_at_login_service_update_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=500, detail=f"Could not update the background service: {exc}"
        ) from exc

    return {"app.start_at_login": value}


def get_widget_show_map() -> dict[str, Any]:
    """The effective value, resolved exactly as `GET /api/widget` resolves it.

    Reading the settings row alone and defaulting to "0" made the Alerts-tab
    checkbox disagree with the widget whenever the row did not exist yet and
    `FINDPLUS_WIDGET_SHOW_MAP=1` was set: the box read off while the widget
    drew the map. `_widget_show_map` is the one resolver (row wins, config
    is the fallback), so both surfaces now answer the same question.
    """
    with session_scope() as session:
        return {"widget.show_map": _widget_show_map(session, get_settings())}


def set_widget_show_map(value: bool = Body(..., embed=True)) -> dict[str, Any]:
    """Persist whether the widget renders a map snapshot.

    Same per-key GET/PUT/POST shape as `app.start_at_login` above. The
    dashboard's Alerts-tab checkbox (web/app/alerts.js) writes this; the
    settings-table row it sets is the same one `GET /api/widget` and
    `findplus widget show-map` read (see `_widget_show_map` in
    api/_widget.py — a table row always wins over the config env var).
    """
    with session_scope() as session:
        set_setting(session, "widget.show_map", "1" if value else "0")
    return {"widget.show_map": value}


def get_onboarding_completed_at() -> dict[str, Any]:
    with session_scope() as session:
        return {"onboarding.completed_at": get_setting(session, "onboarding.completed_at")}


def set_onboarding_completed_at(
    value: str | None = Body(default=None, embed=True),
) -> dict[str, Any]:
    """Stamp or clear the onboarding completion time (specs/onboarding.md § 2).

    `value: null` un-completes onboarding. Only tests and `findplus setup
    --reset` send it; the wizard always sends an ISO timestamp.
    """
    with session_scope() as session:
        set_setting(session, "onboarding.completed_at", value)
    return {"onboarding.completed_at": value}


def get_onboarding_last_step() -> dict[str, Any]:
    with session_scope() as session:
        return {"onboarding.last_step": get_setting(session, "onboarding.last_step")}


def set_onboarding_last_step(
    value: str | None = Body(default=None, embed=True),
) -> dict[str, Any]:
    """Record the wizard's resume point, one of the eight known step ids."""
    try:
        validate_step(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with session_scope() as session:
        set_setting(session, "onboarding.last_step", value)
    return {"onboarding.last_step": value}


def register_key_routes(router: APIRouter) -> None:
    """Attach every per-key route to the /api/settings router."""
    router.add_api_route("/app.start_at_login", get_start_at_login, methods=["GET"])
    router.add_api_route("/app.start_at_login", set_start_at_login, methods=["POST"])
    router.add_api_route("/widget.show_map", get_widget_show_map, methods=["GET"])
    router.add_api_route("/widget.show_map", set_widget_show_map, methods=["PUT"])
    router.add_api_route("/widget.show_map", set_widget_show_map, methods=["POST"])
    router.add_api_route("/onboarding.completed_at", get_onboarding_completed_at, methods=["GET"])
    router.add_api_route("/onboarding.completed_at", set_onboarding_completed_at, methods=["POST"])
    router.add_api_route("/onboarding.last_step", get_onboarding_last_step, methods=["GET"])
    router.add_api_route("/onboarding.last_step", set_onboarding_last_step, methods=["POST"])

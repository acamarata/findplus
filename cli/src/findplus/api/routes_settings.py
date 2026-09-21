"""Settings routes: read/write app settings, PIN set/change/remove.

Purpose    : User-configurable dashboard settings and PIN management.
Inputs     : theme, idle_minutes, lock_enabled, PIN values.
Outputs    : The public (non-secret) settings payload.
Constraints: A PIN change revokes every session, then re-issues one to the caller.
             The per-key GET/POST sub-routes (app.start_at_login,
             widget.show_map, onboarding.*) live in routes_settings_keys.py;
             handlers that need factory collaborators sit in small
             register-functions so no function exceeds the 50-line cap
             (E13 loop-1 refactor; routes and signatures unchanged).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from findplus.appsettings import (
    clear_pin,
    load_settings,
    save_idle_minutes,
    save_pin,
    save_theme,
    set_lock_enabled,
)
from findplus.db.session import session_scope
from findplus.logging_setup import get_logger
from findplus.security import SessionStore, hash_pin, reject_padded_pin, verify_pin
from findplus.state import set_setting

from ._settings_fields import (
    _RETENTION_KEY,
    _raw_patch_body,
    _settings_body,
    _write_config_fields,
    _write_onboarding_fields,
)
from .middleware import same_origin_problem
from .routes_settings_keys import register_key_routes

log = get_logger(__name__)


def _apply_writes(
    session,
    *,
    theme: str | None,
    idle_minutes: int | None,
    lock_enabled: bool | None,
    native_detail: bool | None,
    poll_interval_minutes: int | None,
    retention_days: int | None,
    retention_present: bool,
    raw_body: dict[str, Any],
    completed_at: str | None,
    last_step: str | None,
) -> None:
    """One PATCH's field writes, in the route's original order."""
    if theme is not None:
        save_theme(session, theme)
    if idle_minutes is not None:
        save_idle_minutes(session, idle_minutes)
    if lock_enabled is not None:
        current = load_settings(session)
        if lock_enabled and not current.pin_configured:
            raise HTTPException(
                status_code=400,
                detail="Set a PIN before enabling the app lock.",
            )
        set_lock_enabled(session, lock_enabled)
    if native_detail is not None:
        set_setting(session, "alerts.native_detail", "1" if native_detail else "0")
    try:
        _write_config_fields(poll_interval_minutes, retention_days, retention_present)
        _write_onboarding_fields(session, raw_body, completed_at, last_step)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _pin_change_allowed(request: Request, session, current_pin: str | None) -> None:
    """Prove the caller may rewrite the PIN: the current PIN, or a first-time
    same-origin POST. Raises 403; returns nothing on success."""
    existing = load_settings(session)
    if existing.pin_configured:
        if not verify_pin(current_pin or "", existing.pin_salt or "", existing.pin_hash or ""):
            raise HTTPException(status_code=403, detail="Current PIN is incorrect.")
    else:
        problem = same_origin_problem(request)
        if problem is not None:
            raise HTTPException(status_code=403, detail=problem)


def _reissue_session(
    response: Response,
    *,
    sessions: SessionStore,
    session_cookie: str,
    updated,
    sync_idle_timeout,
) -> None:
    """A PIN change signs every device out and this browser straight back in."""
    sessions.revoke_all()
    sync_idle_timeout(updated)
    response.set_cookie(
        session_cookie,
        sessions.create(),
        httponly=True,
        samesite="strict",
        max_age=None,
        path="/",
    )


def _register_value_routes(router: APIRouter, *, sync_idle_timeout) -> None:
    @router.get("")
    def read_settings() -> dict[str, Any]:
        with session_scope() as session:
            return _settings_body(session)

    @router.patch("")
    def write_settings(
        theme: str | None = Body(default=None, embed=True),
        idle_minutes: int | None = Body(default=None, embed=True),
        lock_enabled: bool | None = Body(default=None, embed=True),
        poll_interval_minutes: int | None = Body(
            default=None, embed=True, alias="poll.interval_minutes"
        ),
        # An explicit wire `null` means "keep history forever" (stored as 0) and
        # an absent key means "leave retention alone". FastAPI gives both the
        # declared default, so which one happened is read off the raw body
        # below, never off this parameter. Do not add a sentinel default here.
        retention_days: int | None = Body(default=None, embed=True, alias="history.retention_days"),
        native_detail: bool | None = Body(default=None, embed=True, alias="alerts.native_detail"),
        completed_at: str | None = Body(default=None, embed=True, alias="onboarding.completed_at"),
        last_step: str | None = Body(default=None, embed=True, alias="onboarding.last_step"),
        raw_body: dict[str, Any] = Depends(_raw_patch_body),
    ) -> dict[str, Any]:
        with session_scope() as session:
            try:
                _apply_writes(
                    session,
                    theme=theme,
                    idle_minutes=idle_minutes,
                    lock_enabled=lock_enabled,
                    native_detail=native_detail,
                    poll_interval_minutes=poll_interval_minutes,
                    retention_days=retention_days,
                    retention_present=_RETENTION_KEY in raw_body,
                    raw_body=raw_body,
                    completed_at=completed_at,
                    last_step=last_step,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            updated = load_settings(session)
            body = _settings_body(session)
        sync_idle_timeout(updated)
        return body


def _register_set_pin_route(
    router: APIRouter, *, sessions: SessionStore, session_cookie: str, sync_idle_timeout
) -> None:
    @router.post("/pin")
    def set_pin(
        request: Request,
        response: Response,
        new_pin: str = Body(..., embed=True),
        current_pin: str | None = Body(default=None, embed=True),
    ) -> dict[str, Any]:
        """Set or change the PIN. Changing it requires the existing one.

        A credential change revokes every existing session, then immediately
        re-issues one to THIS browser. Other devices are signed out; the person
        who just set the PIN is not locked out of the window they set it in.

        The FIRST-time set has no current PIN to prove, so it is the one
        credential write a foreign page could otherwise perform to take the
        lock over. It repeats the same-origin check the OriginGuard already
        applies, so the rule survives any future change to that middleware's
        path matching. Forgetting the PIN is recovered at the console with
        `findplus pin reset --yes`, never over HTTP.
        """
        try:
            reject_padded_pin(new_pin, "new_pin")
            if current_pin is not None:
                reject_padded_pin(current_pin, "current_pin")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with session_scope() as session:
            _pin_change_allowed(request, session, current_pin)
            try:
                salt, digest = hash_pin(new_pin)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            save_pin(session, salt, digest)
            updated = load_settings(session)
        _reissue_session(
            response,
            sessions=sessions,
            session_cookie=session_cookie,
            updated=updated,
            sync_idle_timeout=sync_idle_timeout,
        )
        log.info("pin_updated")
        return updated.public()


def _register_remove_pin_route(router: APIRouter, *, sessions: SessionStore) -> None:
    @router.delete("/pin")
    def remove_pin(current_pin: str = Body(..., embed=True)) -> dict[str, Any]:
        """Remove the PIN and disable the lock. Requires the current PIN.

        `current_pin` travels in the JSON body, never a query parameter, so
        it can never land in a URL or an access log (carry-forward #1, E1
        CR-C ruling — applied here since this is the first ticket to touch
        both this route and web/app/settings.js).
        """
        try:
            reject_padded_pin(current_pin, "current_pin")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with session_scope() as session:
            existing = load_settings(session)
            if not existing.pin_configured:
                return existing.public()
            if not verify_pin(current_pin, existing.pin_salt or "", existing.pin_hash or ""):
                raise HTTPException(status_code=403, detail="Current PIN is incorrect.")
            clear_pin(session)
            updated = load_settings(session)
        sessions.revoke_all()
        log.warning("pin_removed")
        return updated.public()


def build_router(*, sessions: SessionStore, session_cookie: str, sync_idle_timeout) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["settings"])
    _register_value_routes(router, sync_idle_timeout=sync_idle_timeout)
    _register_set_pin_route(
        router,
        sessions=sessions,
        session_cookie=session_cookie,
        sync_idle_timeout=sync_idle_timeout,
    )
    _register_remove_pin_route(router, sessions=sessions)
    register_key_routes(router)
    return router

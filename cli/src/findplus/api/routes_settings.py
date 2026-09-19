"""Settings routes: read/write app settings, PIN set/change/remove.

Purpose    : User-configurable dashboard settings and PIN management.
Inputs     : theme, idle_minutes, lock_enabled, PIN values.
Outputs    : The public (non-secret) settings payload.
Constraints: A PIN change revokes every session, then re-issues one to the caller.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Response

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
from findplus.security import SessionStore, hash_pin, verify_pin

log = get_logger(__name__)


def build_router(*, sessions: SessionStore, session_cookie: str, sync_idle_timeout) -> APIRouter:
    router = APIRouter(prefix="/api/settings")

    @router.get("")
    def read_settings() -> dict[str, Any]:
        with session_scope() as session:
            return load_settings(session).public()

    @router.put("")
    def write_settings(
        theme: str | None = Body(default=None, embed=True),
        idle_minutes: int | None = Body(default=None, embed=True),
        lock_enabled: bool | None = Body(default=None, embed=True),
    ) -> dict[str, Any]:
        with session_scope() as session:
            try:
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
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            updated = load_settings(session)
        sync_idle_timeout(updated)
        return updated.public()

    @router.post("/pin")
    def set_pin(
        response: Response,
        new_pin: str = Body(..., embed=True),
        current_pin: str | None = Body(default=None, embed=True),
    ) -> dict[str, Any]:
        """Set or change the PIN. Changing it requires the existing one.

        A credential change revokes every existing session, then immediately
        re-issues one to THIS browser. Other devices are signed out; the person
        who just set the PIN is not locked out of the window they set it in.
        """
        with session_scope() as session:
            existing = load_settings(session)
            if existing.pin_configured and not verify_pin(
                current_pin or "", existing.pin_salt or "", existing.pin_hash or ""
            ):
                raise HTTPException(status_code=403, detail="Current PIN is incorrect.")
            try:
                salt, digest = hash_pin(new_pin)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            save_pin(session, salt, digest)
            updated = load_settings(session)

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
        log.info("pin_updated")
        return updated.public()

    @router.delete("/pin")
    def remove_pin(current_pin: str = Query(...)) -> dict[str, Any]:
        """Remove the PIN and disable the lock. Requires the current PIN."""
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

    return router

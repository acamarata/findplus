"""App-lock routes: status, unlock, lock, requirements.

Purpose    : PIN-gated session lock for the dashboard. Enforcement lives in the
             SessionAuthMiddleware in api/__init__.py; these routes manage it.
Inputs     : PIN (unlock), the session cookie.
Outputs    : Lock state, a session cookie on unlock.
Constraints: Rate-limited against brute force via SessionStore.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Cookie, HTTPException, Response

from findplus import honesty
from findplus.logging_setup import get_logger
from findplus.security import MIN_PIN_LENGTH, SessionStore, verify_pin

log = get_logger(__name__)


def build_router(
    *,
    sessions: SessionStore,
    session_cookie: str,
    current_lock_state,
    sync_idle_timeout,
) -> APIRouter:
    router = APIRouter(prefix="/api/lock", tags=["lock"])

    @router.get("/status")
    def lock_status(
        session_token: str | None = Cookie(default=None, alias=session_cookie),
    ) -> dict[str, Any]:
        """Whether the app is locked right now. Always reachable."""
        lock_active, app_settings = current_lock_state()
        sync_idle_timeout(app_settings)
        unlocked = not lock_active or sessions.is_valid(session_token, touch=False)
        return {
            "lock_configured": app_settings.pin_configured,
            "lock_enabled": app_settings.lock_enabled,
            "locked": bool(lock_active and not unlocked),
            "idle_minutes": app_settings.idle_minutes,
            "theme": app_settings.theme,
            "retry_after_seconds": round(sessions.seconds_until_retry()),
            "attempts_remaining": sessions.attempts_remaining(),
        }

    @router.post("/unlock")
    def unlock(response: Response, pin: str = Body(..., embed=True)) -> dict[str, Any]:
        """Exchange a correct PIN for a session cookie. Rate-limited."""
        wait = sessions.seconds_until_retry()
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Too many incorrect attempts. Try again in {wait:.0f} seconds.",
            )

        lock_active, app_settings = current_lock_state()
        if not lock_active:
            return {"unlocked": True, "note": "The app lock is not enabled."}

        if not verify_pin(pin, app_settings.pin_salt or "", app_settings.pin_hash or ""):
            sessions.record_failure()
            log.warning("unlock_failed", attempts_remaining=sessions.attempts_remaining())
            raise HTTPException(
                status_code=401,
                detail=(
                    f"Incorrect PIN. {sessions.attempts_remaining()} attempt(s) "
                    "before a 60-second lockout."
                ),
            )

        sessions.clear_failures()
        sync_idle_timeout(app_settings)
        token = sessions.create()
        response.set_cookie(
            session_cookie,
            token,
            httponly=True,
            samesite="strict",
            max_age=None,
            path="/",
        )
        log.info("unlocked")
        return {"unlocked": True, "idle_minutes": app_settings.idle_minutes}

    @router.post("/lock")
    def lock_now(
        response: Response,
        session_token: str | None = Cookie(default=None, alias=session_cookie),
    ) -> dict[str, Any]:
        """Lock immediately (manual button, or the client's idle timer)."""
        sessions.revoke(session_token)
        response.delete_cookie(session_cookie, path="/")
        return {"locked": True}

    @router.get("/requirements")
    def lock_requirements() -> dict[str, Any]:
        return {
            "min_pin_length": MIN_PIN_LENGTH,
            # The specs/honesty.md sentence, not a second wording of it. The
            # Settings dialog renders this (#lock-caveat) directly above
            # /api/config.notices.lock_not_encryption (#fp-notice-lock), so a
            # paraphrase here put two different lock caveats on one screen.
            "caveat": honesty.LOCK_NOT_ENCRYPTION,
        }

    return router

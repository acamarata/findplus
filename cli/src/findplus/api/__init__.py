"""Local REST API + static UI host.

Purpose : Serve the dashboard and its data to a browser on this machine only.
Constraints:
    - Binds to 127.0.0.1. No analytics, telemetry, cookies or third-party scripts.
    - Reading this API never queries Google. The browser may poll it every ~45s;
      Google is queried only by the server-side poller on its own interval.
    - `/api/poll-now` is the single endpoint that can trigger a Google request,
      and it is POST-only and rate-limited.

Split from the original monolithic api.py into a router-per-concern package;
this module owns app assembly, the session-lock middleware, and the two
public constants (FIND_HUB_NOTICE, SESSION_COOKIE) other routers are handed
by parameter so there is exactly one copy of each.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError
from starlette.middleware.base import BaseHTTPMiddleware

from findplus import __version__, honesty
from findplus.appsettings import load_settings
from findplus.config import PROJECT_ROOT, get_settings
from findplus.db.session import session_scope
from findplus.security import SessionStore

from . import (
    routes_alerts_channels,
    routes_alerts_rules,
    routes_core,
    routes_devices,
    routes_groups,
    routes_history,
    routes_lock,
    routes_places,
    routes_providers,
    routes_settings,
)
from ._routes_history_export import build_export_router
from .middleware import OriginGuardMiddleware, SecurityHeadersMiddleware

__all__ = ["SessionAuthMiddleware", "create_app"]


def _static_dir() -> Path:
    """Dashboard assets: packaged copy inside the wheel, else the monorepo `web/` folder."""
    packaged = Path(__file__).parent.parent / "web" / "static"
    return packaged if packaged.exists() else PROJECT_ROOT.parent / "web"


STATIC_DIR = _static_dir()

#: The Find Hub sentence `/api/health`, `/api/config` and `/api/status` carry.
#: Aliased, never re-typed: a second literal copy of an honesty sentence is a
#: copy that can drift from specs/honesty.md while `test_honesty.py` (which
#: only diffs `findplus.honesty`) keeps passing. Every surface reads
#: honesty.py — PROMPT.md §6.
FIND_HUB_NOTICE = honesty.FIND_HUB

SESSION_COOKIE = "findplus_session"

#: Endpoints reachable while the app is locked. Everything else 401s.
#: The lock is enforced HERE, server-side — hiding the UI would leave the data
#: one `curl` away. Corrected to the 8-path set from specs/api-contract.md
#: (renamed from the legacy 3-entry _UNGATED_PATHS, which was under-enforced).
#: `/static/*` and `/` were dead entries: this middleware only inspects paths
#: that start with `/api/`, so neither could ever be compared against, and a
#: literal `"/static/*"` never equals a real request path anyway.
_PUBLIC = frozenset(
    {
        "/api/health",
        "/api/version",
        "/api/lock/status",
        "/api/lock/unlock",
        "/api/lock/lock",
        "/api/lock/requirements",
    }
)


#: Guards manual polls so the UI cannot be used to hammer Google. Process-wide
#: (not per-app-instance), matching the pre-split module-level state in the
#: monolithic api.py; the route handler lives in routes_history.py but reads
#: and writes these names on THIS module so `findplus.api._last_manual_poll`
#: stays a valid patch point (cli/tests/test_api.py monkeypatches it).
_manual_poll_lock = threading.Lock()
_last_manual_poll: datetime | None = None
MANUAL_POLL_COOLDOWN = timedelta(seconds=60)


def _check_poll_cooldown() -> float:
    """0.0 if a manual poll may proceed now (and records it); else seconds to wait."""
    global _last_manual_poll
    with _manual_poll_lock:
        now = datetime.now(UTC)
        if _last_manual_poll and now - _last_manual_poll < MANUAL_POLL_COOLDOWN:
            return (MANUAL_POLL_COOLDOWN - (now - _last_manual_poll)).total_seconds()
        _last_manual_poll = now
        return 0.0


def _current_lock_state():
    """(is_locked_overall, AppSettings). Cheap enough to call per request.

    Fails CLOSED on an unmigrated database. api/_widget.py catches the same
    OperationalError and degrades to an empty read, but this function backs the
    auth middleware: answering "not locked" because the table is missing would
    open every gated route. A typed 503 naming the repair command is the only
    safe answer, and it replaces the uncaught 500 this used to raise.
    """
    try:
        with session_scope() as session:
            app_settings = load_settings(session)
    except OperationalError as exc:
        raise HTTPException(
            status_code=503, detail="Database not migrated. Run findplus db upgrade."
        ) from exc
    return app_settings.lock_active, app_settings


def _sync_idle_timeout(sessions: SessionStore):
    def sync(app_settings) -> None:
        sessions.idle_timeout_seconds = app_settings.idle_minutes * 60

    return sync
class SessionAuthMiddleware(BaseHTTPMiddleware):
    """Return 401 for every gated API path while the app is locked.

    Static assets and the shell page still load — they render the lock
    screen — but no location data crosses this boundary until unlocked.
    """

    def __init__(self, app, sessions: SessionStore):
        super().__init__(app)
        self.sessions = sessions

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or path in _PUBLIC:
            return await call_next(request)

        try:
            lock_active, app_settings = _current_lock_state()
        except HTTPException as exc:
            # BaseHTTPMiddleware sits OUTSIDE Starlette's ExceptionMiddleware, so an
            # HTTPException raised here is never turned into a response — it would
            # surface as a 500. Render it here instead.
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        if not lock_active:
            return await call_next(request)

        self.sessions.idle_timeout_seconds = app_settings.idle_minutes * 60
        token = request.cookies.get(SESSION_COOKIE)
        if self.sessions.is_valid(token):
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Locked. Enter your PIN to continue.", "locked": True},
        )


def create_app(sessions: SessionStore | None = None) -> FastAPI:
    settings = get_settings()
    sessions = sessions or SessionStore()
    app = FastAPI(
        title="Find+",
        version=__version__,
        description="Local Find Hub location history. Not for emergency use.",
        # Swagger UI and ReDoc fetch their JS/CSS from cdn.jsdelivr.net and a
        # favicon from fastapi.tiangolo.com — invariant 9 forbids third-party
        # scripts, and the CSP would blank the page anyway. The machine-
        # readable schema stays: it is authed and serves no remote asset.
        # The API reference for humans lives in .github/wiki/API-reference.md.
        docs_url=None,
        redoc_url=None,
        # Schema lives under /api/ so the app lock covers it; at the FastAPI
        # default (/openapi.json) it sat outside the gated prefix and
        # described every route to anyone who could reach the port.
        openapi_url="/api/openapi.json",
    )
    # Registration order is inside-out: the LAST middleware added runs FIRST,
    # so a foreign Host is refused before the lock, the routers or /static see
    # it, and the security headers land on that refusal too.
    app.add_middleware(SessionAuthMiddleware, sessions=sessions)
    app.add_middleware(OriginGuardMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    sync_idle_timeout = _sync_idle_timeout(sessions)

    app.include_router(
        routes_core.build_router(
            settings=settings, static_dir=STATIC_DIR, find_hub_notice=FIND_HUB_NOTICE
        )
    )
    app.include_router(
        routes_lock.build_router(
            sessions=sessions,
            session_cookie=SESSION_COOKIE,
            current_lock_state=_current_lock_state,
            sync_idle_timeout=sync_idle_timeout,
        )
    )
    app.include_router(
        routes_settings.build_router(
            sessions=sessions,
            session_cookie=SESSION_COOKIE,
            sync_idle_timeout=sync_idle_timeout,
        )
    )
    app.include_router(routes_devices.build_router(settings=settings))
    app.include_router(routes_providers.build_router())
    app.include_router(routes_places.build_router())
    app.include_router(routes_groups.build_router())
    app.include_router(routes_alerts_channels.build_router())
    app.include_router(routes_alerts_rules.build_router())
    app.include_router(
        routes_history.build_router(settings=settings, check_poll_cooldown=_check_poll_cooldown)
    )
    app.include_router(build_export_router())

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()

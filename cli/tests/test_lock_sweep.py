"""Parametrised sweep: every non-public API route must 401 while locked.

Purpose    : Make the lock invariant self-enforcing (api-contract.md §Lock) — a
             route added in a later epic and never added to `_PUBLIC` fails this
             sweep automatically instead of silently leaking data.
Inputs     : The live FastAPI route table from `create_app()`.
Outputs    : One parametrised pytest case per (method, path) pair.
Constraints: Built at module scope so pytest names each route in its node ID;
             path params are replaced with "0" since the lock fires before
             FastAPI parses them.
"""

from __future__ import annotations

import re

import pytest

from tests.test_api_routes_snapshot import _app_routes

#: Mirrors api-contract.md §Lock exactly. /static/* and / are excluded below by
#: their own path checks, not by being listed here.
_PUBLIC = {
    "/api/health",
    "/api/version",
    "/api/lock/status",
    "/api/lock/unlock",
    "/api/lock/lock",
    "/api/lock/requirements",
}


def _collect_routes() -> list[tuple[str, str]]:
    """Every (method, path) pair the app actually serves, minus public/static/docs.

    `app.routes` does not expose plain `APIRoute`s for an `include_router()`
    call on this FastAPI version — each becomes an opaque `_IncludedRouter`
    wrapper with no `.methods` of its own. `_app_routes()` (from the route-
    count regression guard) already flattens those wrappers via
    `original_router.routes` and drops FastAPI's own schema/docs routes;
    reused here rather than re-implementing the same recursion.
    """
    from findplus.api import create_app

    return sorted(
        (method, route.path)
        for route in _app_routes(create_app())
        for method in route.methods
        if route.path != "/" and route.path not in _PUBLIC and not _is_helper_page(route.path)
    )


def _is_helper_page(path: str) -> bool:
    """The daemon-served Chrome-helper begin/success pages are plain HTML with
    no location data, opened in the user's own Chrome (which has no session
    cookie), so they are public by design and never lock-gated."""
    return path in {
        "/auth/google/begin",
        "/auth/google/unlock/begin",
        "/auth/google/success",
        # Ingest routes the extension posts to without a cookie; each has its
        # own gate (extension origin + single-use state), see _STATE_GATED.
        "/api/auth/google/helper/token",
        "/api/auth/google/helper/unlock",
        "/api/auth/google/helper/seen",
        # The in-app sign-in window's shell posts: pinned shell headers + state.
        "/api/auth/google/native/token",
        "/api/auth/google/native/unlock",
        "/api/auth/google/native/event",
        "/api/auth/google/native/classify",
        # Automatic updates install while locked: status names no paths or places,
        # and apply needs the desktop shell's own header (routes_update.py).
        "/api/update/status",
        "/api/update/apply",
    }


_NON_PUBLIC_ROUTES = _collect_routes()


@pytest.mark.parametrize("method,path", _NON_PUBLIC_ROUTES)
def test_locked_returns_401(locked_client, method: str, path: str) -> None:
    concrete = re.sub(r"\{[^}]+\}", "0", path)
    resp = getattr(locked_client, method.lower())(concrete)
    assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"
    assert resp.json() == {"detail": "Locked. Enter your PIN to continue.", "locked": True}

"""Route-inventory regression guard for the api/ package split.

Purpose    : Catch a route silently dropped or renamed when the api/ package
             grows in later epics (E6-E8 add places/groups/alerts routers).
Inputs     : A freshly built FastAPI app via create_app().
Outputs    : Assertions on the route count and path set.
Constraints: Zero behavior change from the pre-split monolith is the bar —
             this pinned the exact 24-route surface at the end of E1-T4;
             E3-T5 adds GET /api/providers, bringing it to 25; E4-T5 adds the
             6 /api/places routes, bringing it to 31; E8-T2 adds
             GET /api/version and GET /api/widget, bringing it to 33; E5-T4
             adds the 7 /api/groups routes, bringing it to 40; E6-T5 adds the
             12 /api/alerts/* routes, bringing it to 52; E13-T5 adds
             GET/POST /api/settings/app.start_at_login, bringing it to 54;
             P1-E10-S2's fix loop adds GET/PUT/POST
             /api/settings/widget.show_map, bringing it to 57;
             P2-E2-W2-S1-T2 adds PATCH /api/devices/{device_id} and
             GET /api/icons, bringing it to 59; P2-E6-W3-S1-T2 adds
             GET /api/auth/status and the two /api/auth/google/* routes,
             bringing it to 62; P2-E6-W3-S1-T3 adds the three
             /api/auth/apple/* routes, bringing it to 65; P2-E6-W3-S1-T4 adds
             POST /api/apple/accessories, bringing it to 66;
             P2-E8-W3-S1-T3 adds PUT/DELETE
             /api/alerts/channels/whatsapp, bringing it to 68;
             P2-E8-W3-S1-T4 adds POST
             /api/alerts/deliveries/{delivery_id}/ack, bringing it to 69.
"""

from __future__ import annotations

from findplus.api import create_app

#: FastAPI's own schema route (openapi.json) — not part of the application's
#: route surface this test pins. It sits under /api/ so the app lock covers
#: it (security fix 10). Swagger UI/ReDoc are disabled (docs_url=None,
#: redoc_url=None): they fetch JS/CSS from cdn.jsdelivr.net and a favicon
#: from fastapi.tiangolo.com, which invariant 9 forbids.
_FASTAPI_BUILTIN_PATHS = {
    "/api/openapi.json",
}


def _flatten(routes):
    found = []
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            found.extend(_flatten(nested.routes))
        elif hasattr(route, "methods") and route.methods:
            found.append(route)
    return found


def _app_routes(app):
    """Flatten FastAPI's lazy `_IncludedRouter` wrappers into concrete routes.

    FastAPI >=0.14x wraps each `include_router()` call in a proxy object so
    `app.routes` no longer holds plain APIRoute instances for included
    routers (only for routes registered directly on `app`, which this repo
    no longer does since the api/ package split). Recurse through
    `original_router.routes` to reach the real routes, matching how earlier
    FastAPI versions exposed `app.routes` and how the pre-split monolith's
    directly-decorated routes always behaved.
    """
    return [r for r in _flatten(app.routes) if r.path not in _FASTAPI_BUILTIN_PATHS]


def test_route_count():
    app = create_app()
    routes = _app_routes(app)
    assert len(routes) == 69


def test_route_paths_present():
    app = create_app()
    paths = {r.path for r in _app_routes(app)}
    expected = {
        "/",
        "/api/health",
        "/api/config",
        "/api/status",
        "/api/lock/status",
        "/api/lock/unlock",
        "/api/lock/lock",
        "/api/lock/requirements",
        "/api/settings",
        "/api/settings/pin",
        "/api/settings/app.start_at_login",
        "/api/settings/widget.show_map",
        "/api/devices",
        "/api/devices/refresh",
        "/api/devices/track",
        "/api/devices/default",
        "/api/devices/{device_id}",
        "/api/icons",
        "/api/timeline",
        "/api/days",
        "/api/latest",
        "/api/poll-runs",
        "/api/poll-now",
        "/api/export",
        "/api/history/delete-before",
        "/api/history/clear",
        "/api/providers",
        "/api/auth/status",
        "/api/auth/google/start",
        "/api/auth/google/progress",
        "/api/auth/apple/start",
        "/api/auth/apple/code",
        "/api/auth/apple/progress",
        "/api/apple/accessories",
        "/api/places",
        "/api/places/{place_id}",
        "/api/places/events",
        "/api/places/presence",
        "/api/version",
        "/api/widget",
        "/api/groups",
        "/api/groups/{group_id}",
        "/api/groups/{group_id}/members",
        "/api/groups/{group_id}/presence",
        "/api/groups/events",
        "/api/alerts/channels",
        "/api/alerts/channels/telegram",
        "/api/alerts/channels/telegram/setup",
        "/api/alerts/channels/webhook",
        "/api/alerts/channels/whatsapp",
        "/api/alerts/test",
        "/api/alerts/rules",
        "/api/alerts/rules/{rule_id}",
        "/api/alerts/deliveries",
        "/api/alerts/deliveries/{delivery_id}/ack",
    }
    assert expected.issubset(paths)


def test_no_docs_or_redoc_routes_registered():
    """docs_url and redoc_url are None (see api/__init__.py); confirm neither
    Swagger UI, ReDoc nor the OAuth2 redirect route ever gets registered."""
    app = create_app()
    all_paths = {r.path for r in _flatten(app.routes)}
    assert "/api/docs" not in all_paths
    assert "/docs" not in all_paths
    assert "/redoc" not in all_paths
    assert "/api/docs/oauth2-redirect" not in all_paths

"""The bare FastAPI() object create_app() configures further.

Purpose    : Split out of api/__init__.py (PRI hard rule 7: <=300 lines/file)
             once create_app() needed a second helper to stay under the
             function-length cap too.
Inputs     : The app version string.
Outputs    : A FastAPI instance with docs disabled and its schema kept
             behind the app lock.
Constraints: Pure construction -- no middleware, no routers, no static
             mount. create_app() in api/__init__.py still owns those, in the
             exact inside-out order invariant 9's Host guard depends on.
"""

from __future__ import annotations

from fastapi import FastAPI


def new_fastapi_app(version: str) -> FastAPI:
    """The bare FastAPI object, docs disabled, schema kept behind the lock.

    Swagger UI and ReDoc fetch their JS/CSS from cdn.jsdelivr.net and a
    favicon from fastapi.tiangolo.com — invariant 9 forbids third-party
    scripts, and the CSP would blank the page anyway. The machine-readable
    schema stays: it is authed and serves no remote asset. The API reference
    for humans lives in .github/wiki/API-reference.md. Schema lives under
    /api/ so the app lock covers it; at the FastAPI default (/openapi.json)
    it sat outside the gated prefix and described every route to anyone who
    could reach the port.
    """
    return FastAPI(
        title="Find+",
        version=version,
        description="Local Find Hub location history. Not for emergency use.",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

"""OriginGuardMiddleware sweep: every mutating /api/ route, all three
cross-site header shapes, plus the two legitimate ones (blind cap B3).

Purpose : POST /api/apple/accessories is deliberately not behind
          `_require_origin_signal` (routes_auth.py) so the CLI/MCP's
          headerless requests still reach it, "the way every other mutating
          route is" per that route's own comment. Before this fix, a request
          carrying only a `Referer` header -- exactly what an old-style
          cross-site `<form>` POST sends when it never sets `Origin` or
          `Sec-Fetch-Site` -- reached every such route unchecked, because
          `same_origin_problem()` only ever looked at those two headers.
          This discovers every mutating route from the live route table
          instead of hand-listing them, so a route added later is covered
          automatically, the same pattern test_lock_sweep.py uses for the
          app lock.
Inputs  : The live FastAPI route table from `create_app()`.
Constraints: Path params are replaced with "0"; OriginGuardMiddleware runs
          before routing resolves them, the same way the lock sweep's does.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from tests.api._auth_helpers import SAME_ORIGIN_HEADERS
from tests.test_api_routes_snapshot import _app_routes

EVIL_ORIGIN = "http://evil.example"
EVIL_REFERER = "http://evil.example/attack.html"

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _mutating_routes() -> list[tuple[str, str]]:
    return sorted(
        (method, route.path)
        for route in _app_routes(create_app())
        for method in route.methods
        if method in _MUTATING_METHODS
    )


_ROUTES = _mutating_routes()

#: The three sign-in starters `_require_origin_signal` (routes_auth.py) gates
#: on top of OriginGuardMiddleware: they 403 a headerless request on purpose,
#: unlike every other mutating route. Already pinned by
#: test_auth_route_security.py's own parametrised case; excluded from the
#: headerless-must-pass assertion here so this sweep does not re-litigate it.
_REQUIRES_OWN_SIGNAL = {
    ("POST", "/api/auth/google/start"),
    ("POST", "/api/auth/apple/start"),
    ("POST", "/api/auth/apple/code"),
}
_HEADERLESS_ROUTES = [r for r in _ROUTES if r not in _REQUIRES_OWN_SIGNAL]


@pytest.fixture
def client(tmp_db):
    # Closeout C-M1: bind explicitly to 8647 -- SAME_ORIGIN_HEADERS asserts
    # against that literal Origin.
    return TestClient(create_app(bound_host="127.0.0.1", bound_port=8647))


def test_the_sweep_finds_the_full_mutating_surface() -> None:
    """A floor, not a pinned count: the route surface grows every epic."""
    assert len(_ROUTES) > 15, _ROUTES
    assert ("POST", "/api/apple/accessories") in _ROUTES


@pytest.mark.parametrize("method,path", _ROUTES)
@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": EVIL_ORIGIN},
        {"Sec-Fetch-Site": "cross-site"},
        {"Referer": EVIL_REFERER},
    ],
    ids=["foreign-origin", "cross-site-sec-fetch-site", "foreign-referer-only"],
)
def test_every_mutating_route_refuses_all_three_cross_site_shapes(
    client: TestClient, method: str, path: str, headers: dict[str, str]
) -> None:
    """Three distinct browser shapes an evil.example page can send, none
    carrying same-site proof. `POST /api/apple/accessories` is in this sweep
    like every other route -- it has no route-level guard of its own, so
    refusal here comes entirely from OriginGuardMiddleware."""
    concrete = re.sub(r"\{[^}]+\}", "0", path)
    res = client.request(method, concrete, headers=headers, json={})
    assert res.status_code == 403, f"{method} {path} {headers} -> {res.status_code}"


@pytest.mark.parametrize("method,path", _ROUTES)
def test_every_mutating_route_still_reaches_its_handler_same_origin(
    client: TestClient, method: str, path: str
) -> None:
    """The dashboard's own fetch(): same-origin browser request, must pass."""
    concrete = re.sub(r"\{[^}]+\}", "0", path)
    res = client.request(method, concrete, headers=SAME_ORIGIN_HEADERS, json={})
    assert res.status_code != 403, f"{method} {path} -> {res.status_code}"


@pytest.mark.parametrize("method,path", _HEADERLESS_ROUTES)
def test_every_mutating_route_still_reaches_its_handler_headerless(
    client: TestClient, method: str, path: str
) -> None:
    """The CLI/MCP shape: no Origin, no Sec-Fetch-Site, no Referer at all --
    the Referer fallback must not catch a caller that never sends one. The
    three sign-in starters are excluded: they require SOME signal by their
    own, older guard (`_require_origin_signal`), pinned separately by
    test_auth_route_security.py."""
    concrete = re.sub(r"\{[^}]+\}", "0", path)
    res = client.request(method, concrete, json={})
    assert res.status_code != 403, f"{method} {path} -> {res.status_code}"


# ------------------------------------------------------- the reported route
def test_accessories_refuses_a_cross_site_multipart_post_with_only_a_referer(
    client: TestClient,
) -> None:
    """The exact shape from blind cap B3: a multipart POST (what an HTML
    `<form enctype="multipart/form-data">` on evil.example sends), no Origin,
    no Sec-Fetch-Site, only a foreign Referer."""
    res = client.post(
        "/api/apple/accessories",
        headers={"Referer": EVIL_REFERER},
        data={"name": "x"},
        files={"plist": ("a.plist", b"not a real plist")},
    )
    assert res.status_code == 403


def test_accessories_still_accepts_a_headerless_multipart_post(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: the same body, with no cross-site signal at all, must
    still reach the handler (it may still fail on the plist content itself,
    just not on headers)."""
    monkeypatch.setattr("findplus.providers.apple_findmy.is_available", lambda: (True, ""))
    res = client.post(
        "/api/apple/accessories",
        data={"name": "x"},
        files={"plist": ("a.plist", b"not a real plist")},
    )
    assert res.status_code != 403

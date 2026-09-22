"""OriginGuardMiddleware Host sweep (CF-P2-3): rebinding Hosts, on both GET
and POST, plus the port-exact tightening of `is_allowed_host`/`is_allowed_origin`.

Purpose    : Before this fix, `is_allowed_host` checked the Host header's
             hostname but accepted any port, and `is_allowed_origin` accepted
             a loopback Origin at any port too. A DNS-rebinding page that put
             the daemon's own hostname in its URL but a different (or no)
             port would still have been refused by hostname alone in most
             shapes, but the port itself was never actually checked -- this
             sweep pins that the Host guard now runs before routing, for
             every method, and rejects a wrong port exactly like a wrong
             hostname.
Inputs     : The live FastAPI app via TestClient, with an explicit Host
             header per case; GET covers the dashboard shell and a read
             route, POST covers a mutating route.
Constraints: OriginGuardMiddleware runs before SessionAuthMiddleware, so a
             423/401 lock response never masks a 421 here -- the routes
             below are deliberately ones that would otherwise answer 200.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app

CONFIGURED_PORT = 8647

#: (method, path) pairs covering a read route and a mutating one, plus the
#: dashboard shell itself -- the guard applies to every path, not just /api/.
_ROUTES = [
    ("GET", "/"),
    ("GET", "/api/health"),
    ("POST", "/api/history/clear"),
]


@pytest.fixture
def client(tmp_db) -> TestClient:
    return TestClient(create_app())


def _request(client: TestClient, method: str, path: str, host: str | None):
    headers = {} if host is None else {"Host": host}
    if method == "GET":
        return client.get(path, headers=headers)
    return client.request(method, path, headers=headers, json={"confirm": False})


@pytest.mark.parametrize("method,path", _ROUTES)
@pytest.mark.parametrize(
    "host",
    ["evil.example:8647", "evil.example", "127.0.0.1.evil.com:8647"],
    ids=["rebound-hostname-right-port", "rebound-hostname-no-port", "lookalike-prefix"],
)
def test_a_rebinding_host_is_refused_on_every_method(
    client: TestClient, method: str, path: str, host: str
) -> None:
    res = _request(client, method, path, host)
    assert res.status_code == 421, f"{method} {path} Host={host} -> {res.status_code}"
    assert "location" not in res.text.lower()


@pytest.mark.parametrize("method,path", _ROUTES)
@pytest.mark.parametrize(
    "host",
    ["127.0.0.1:9999", "localhost:1", "[::1]:80", "127.0.0.1"],
    ids=["loopback-wrong-port", "localhost-wrong-port", "ipv6-wrong-port", "bare-loopback-no-port"],
)
def test_a_loopback_host_on_the_wrong_port_is_refused(
    client: TestClient, method: str, path: str, host: str
) -> None:
    """The daemon only answers on `CONFIGURED_PORT`; a rebinding page can put
    any port it likes in its URL, so the right hostname is not enough."""
    res = _request(client, method, path, host)
    assert res.status_code == 421, f"{method} {path} Host={host} -> {res.status_code}"


@pytest.mark.parametrize("method,path", _ROUTES)
@pytest.mark.parametrize(
    "host",
    [f"127.0.0.1:{CONFIGURED_PORT}", f"localhost:{CONFIGURED_PORT}", f"[::1]:{CONFIGURED_PORT}"],
    ids=["ipv4-loopback", "localhost", "ipv6-loopback"],
)
def test_a_legitimate_loopback_host_still_reaches_the_handler(
    client: TestClient, method: str, path: str, host: str
) -> None:
    res = _request(client, method, path, host)
    assert res.status_code != 421, f"{method} {path} Host={host} -> {res.status_code}"


@pytest.mark.parametrize("method,path", _ROUTES)
@pytest.mark.parametrize(
    "host",
    [f"localhost.:{CONFIGURED_PORT}", f"127.0.0.1.:{CONFIGURED_PORT}"],
    ids=["localhost-trailing-dot", "ipv4-loopback-trailing-dot"],
)
def test_a_trailing_dot_loopback_host_still_reaches_the_handler(
    client: TestClient, method: str, path: str, host: str
) -> None:
    """G4: the absolute-FQDN form (a trailing dot after the hostname) is the
    same host to DNS and must not be refused just because it doesn't exactly
    match LOOPBACK_HOSTNAMES."""
    res = _request(client, method, path, host)
    assert res.status_code != 421, f"{method} {path} Host={host} -> {res.status_code}"


@pytest.mark.parametrize("method,path", _ROUTES)
def test_a_missing_host_header_is_refused(client: TestClient, method: str, path: str) -> None:
    """An empty Host is what `is_allowed_host(None, ...)` models: httpx will
    not send a request with no Host header at all, so this is the closest a
    test can get to the "missing" case the middleware itself always guards
    against with `if not host_header`."""
    res = _request(client, method, path, "")
    assert res.status_code == 421, f"{method} {path} -> {res.status_code}"


@pytest.mark.parametrize("method,path", _ROUTES)
def test_a_bare_testserver_host_is_still_refused_in_production_settings(
    client: TestClient, method: str, path: str
) -> None:
    """`http://testserver` is httpx/Starlette's own TestClient default base_url,
    and this suite only avoids tripping on it because conftest.py's `client`
    fixture overrides it to a real loopback Host (LOOPBACK_BASE_URL). Nothing
    about `is_allowed_host` itself special-cases it: it is exactly the shape
    a rebinding page would use (a hostname that is not 127.0.0.1/localhost,
    no configured port), and this pins that the production guard still
    refuses it, independent of whatever a test's own client happens to send."""
    res = _request(client, method, path, "testserver")
    assert res.status_code == 421, f"{method} {path} Host=testserver -> {res.status_code}"

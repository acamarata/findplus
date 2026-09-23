"""Regression tests for the blind security review of the local API.

Every test here reproduces the attack first and then asserts it is refused, so
a later change that removes a guard fails loudly rather than quietly.

Covered here: DNS rebinding (Host), cross-origin reads and writes (Origin,
Sec-Fetch-Site), first-PIN takeover. Response headers, the OpenAPI schema
lock, webhook-URL masking, Content-Disposition and the composed-page/static
guards moved to test_security_guards_responses.py (E13 stage 2, size cap).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from findplus.api.middleware import is_allowed_host, is_allowed_origin
from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from findplus.state import track_devices
from tests.conftest import make_observation

EVIL = "http://evil.example.com"


@pytest.fixture
def client(tmp_db):
    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2")
        track_devices(session, ["TAG-001"], exclusive=True)
        ingest_observations(session, [make_observation(minutes=0)])
    # Closeout C-M1: bind explicitly to 8647 -- this file's Host/Origin
    # parametrizations assert against that literal port.
    return TestClient(create_app(bound_host="127.0.0.1", bound_port=8647))


# ------------------------------------------------------- 1. DNS rebinding
def test_a_rebound_hostname_cannot_reach_the_api(client: TestClient) -> None:
    """The attack: evil.example.com re-resolves to 127.0.0.1, the victim's
    browser connects to this daemon and sends Host: evil.example.com."""
    res = client.get("/api/status", headers={"Host": "evil.example.com"})
    assert res.status_code == 421
    assert "location" not in res.text.lower()


def test_a_rebound_hostname_cannot_reach_the_dashboard(client: TestClient) -> None:
    assert client.get("/", headers={"Host": "evil.example.com"}).status_code == 421


@pytest.mark.parametrize("host", ["127.0.0.1:8647", "localhost:8647", "[::1]:8647"])
def test_loopback_hostnames_are_accepted(client: TestClient, host: str) -> None:
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:9999", "localhost:1", "[::1]:80"])
def test_loopback_hostnames_on_the_wrong_port_are_refused(client: TestClient, host: str) -> None:
    """CF-P2-3: hostname alone used to be enough. A bare Host (implied port 80)
    or an explicit port other than the daemon's own is now refused the same
    as a foreign hostname -- a rebinding page can put any port it likes in
    the URL, and this daemon only ever answers on one."""
    assert client.get("/api/health", headers={"Host": host}).status_code == 421


def test_host_helper_rejects_lookalikes() -> None:
    assert is_allowed_host("127.0.0.1.evil.com", "127.0.0.1", 8647) is False
    assert is_allowed_host("localhost.evil.com:8647", "127.0.0.1", 8647) is False
    assert is_allowed_host(None, "127.0.0.1", 8647) is False


def test_host_helper_requires_the_configured_port() -> None:
    assert is_allowed_host("127.0.0.1:8647", "127.0.0.1", 8647) is True
    assert is_allowed_host("127.0.0.1:9999", "127.0.0.1", 8647) is False
    assert is_allowed_host("127.0.0.1", "127.0.0.1", 8647) is False
    assert is_allowed_host("127.0.0.1", "127.0.0.1", 80) is True


# ----------------------------------------------------------- 1/8. origins
def test_a_foreign_origin_cannot_read_the_api(client: TestClient) -> None:
    res = client.get("/api/status", headers={"Origin": EVIL})
    assert res.status_code == 403


def test_a_foreign_origin_cannot_write(client: TestClient) -> None:
    res = client.post("/api/history/clear", json={"confirm": True}, headers={"Origin": EVIL})
    assert res.status_code == 403


def test_a_cross_site_mutation_is_refused_even_without_an_origin(client: TestClient) -> None:
    """Finding 8: a form POST from another page carries Sec-Fetch-Site."""
    res = client.post(
        "/api/history/clear",
        json={"confirm": True},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert res.status_code == 403


def test_the_dashboards_own_requests_pass(client: TestClient) -> None:
    res = client.post(
        "/api/history/clear",
        json={"confirm": False},
        headers={"Origin": "http://127.0.0.1:8647", "Sec-Fetch-Site": "same-origin"},
    )
    assert res.status_code == 200


def test_the_tauri_shell_origin_passes(client: TestClient) -> None:
    assert client.get("/api/status", headers={"Origin": "tauri://localhost"}).status_code == 200


def test_the_cli_and_mcp_send_no_origin_and_are_unaffected(client: TestClient) -> None:
    """The MCP server and `findplus` itself are plain httpx callers."""
    assert client.get("/api/status").status_code == 200
    assert client.post("/api/history/clear", json={"confirm": False}).status_code == 200


def test_origin_helper_accepts_loopback_and_rejects_the_rest() -> None:
    base = "http://127.0.0.1:8647"
    assert is_allowed_origin("http://localhost:8647", base) is True
    assert is_allowed_origin("http://[::1]:8647", base) is True
    assert is_allowed_origin("null", base) is False
    assert is_allowed_origin("http://127.0.0.1.evil.com", base) is False


def test_origin_helper_requires_the_configured_port() -> None:
    """CF-P2-3: a loopback origin used to be accepted at any port. Some other
    local process on a different port is still a real machine, but not
    necessarily this daemon's own page, so only its own port is trusted now."""
    base = "http://127.0.0.1:8647"
    assert is_allowed_origin("http://localhost:3000", base) is False
    assert is_allowed_origin("http://127.0.0.1:9999", base) is False
    assert is_allowed_origin("http://127.0.0.1", base) is False


def test_origin_helper_survives_an_unbracketed_ipv6_base_url() -> None:
    """C-m1: FINDPLUS_HOST=::1 (a loopback the Host guard already accepts)
    builds base_url as "http://::1:8647" -- unbracketed. urlsplit reads the
    extra colons as more host:port separators and used to raise ValueError
    out of _port_of the moment any Origin header arrived at all, turning a
    same-origin check into a 500 instead of a 200/403."""
    base = "http://::1:8647"
    assert is_allowed_origin("http://[::1]:8647", base) is True
    assert is_allowed_origin(EVIL, base) is False
    assert is_allowed_origin("http://[::1]:9999", base) is False


def test_an_ipv6_bound_daemon_answers_origin_requests_without_a_500(tmp_db) -> None:
    """The end-to-end shape of C-m1's repro: bind to ::1, send an Origin
    header, and the guard must 200/403 -- never 500."""
    ipv6_client = TestClient(create_app(bound_host="::1", bound_port=8647))
    same_origin = ipv6_client.get("/api/health", headers={"Origin": "http://[::1]:8647"})
    assert same_origin.status_code == 200, same_origin.text
    foreign = ipv6_client.get("/api/health", headers={"Origin": EVIL})
    assert foreign.status_code == 403, foreign.text


# ------------------------------------------------- 2. first-PIN takeover
def test_a_foreign_page_cannot_claim_the_first_pin(client: TestClient) -> None:
    """The attack: no PIN is set yet, so no current PIN is required; a page on
    another origin sets one and locks the owner out of their own history."""
    res = client.post("/api/settings/pin", json={"new_pin": "666666"}, headers={"Origin": EVIL})
    assert res.status_code == 403
    assert client.get("/api/settings").json()["pin_configured"] is False


def test_a_cross_site_first_pin_set_is_refused(client: TestClient) -> None:
    res = client.post(
        "/api/settings/pin",
        json={"new_pin": "666666"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert res.status_code == 403


def test_the_owner_can_still_set_the_first_pin(client: TestClient) -> None:
    res = client.post(
        "/api/settings/pin",
        json={"new_pin": "864213"},
        headers={"Origin": "http://127.0.0.1:8647", "Sec-Fetch-Site": "same-origin"},
    )
    assert res.status_code == 200
    assert res.json()["pin_configured"] is True


def test_short_pins_are_refused_by_the_api(client: TestClient) -> None:
    assert client.post("/api/settings/pin", json={"new_pin": "8642"}).status_code == 400

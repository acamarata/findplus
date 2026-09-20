"""Regression tests for the blind security review of the local API.

Every test here reproduces the attack first and then asserts it is refused, so
a later change that removes a guard fails loudly rather than quietly.

Covered: DNS rebinding (Host), cross-origin reads and writes (Origin,
Sec-Fetch-Site), first-PIN takeover, the response security headers, the app
lock now covering the OpenAPI schema, webhook-URL masking and the
Content-Disposition filename.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from findplus.api.downloads import content_disposition, slugify_filename
from findplus.api.middleware import (
    CONTENT_SECURITY_POLICY,
    is_allowed_host,
    is_allowed_origin,
)
from findplus.api.routes_alerts_channels import mask_url
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
    return TestClient(create_app())


# ------------------------------------------------------- 1. DNS rebinding
def test_a_rebound_hostname_cannot_reach_the_api(client: TestClient) -> None:
    """The attack: evil.example.com re-resolves to 127.0.0.1, the victim's
    browser connects to this daemon and sends Host: evil.example.com."""
    res = client.get("/api/status", headers={"Host": "evil.example.com"})
    assert res.status_code == 421
    assert "location" not in res.text.lower()


def test_a_rebound_hostname_cannot_reach_the_dashboard(client: TestClient) -> None:
    assert client.get("/", headers={"Host": "evil.example.com"}).status_code == 421


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8647", "localhost:8647", "[::1]:8647"])
def test_loopback_hostnames_are_accepted(client: TestClient, host: str) -> None:
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_host_helper_rejects_lookalikes() -> None:
    assert is_allowed_host("127.0.0.1.evil.com", "127.0.0.1") is False
    assert is_allowed_host("localhost.evil.com:8647", "127.0.0.1") is False
    assert is_allowed_host(None, "127.0.0.1") is False


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
    assert is_allowed_origin("http://localhost:3000", base) is True
    assert is_allowed_origin("http://127.0.0.1:9999", base) is True
    assert is_allowed_origin("null", base) is False
    assert is_allowed_origin("http://127.0.0.1.evil.com", base) is False


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


# ------------------------------------------------------ 9. response headers
def test_every_response_carries_the_security_headers(client: TestClient) -> None:
    res = client.get("/")
    assert res.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["x-content-type-options"] == "nosniff"


def test_the_csp_allows_only_self_and_the_tile_host() -> None:
    assert "default-src 'self'" in CONTENT_SECURITY_POLICY
    assert "https://tile.openstreetmap.org" in CONTENT_SECURITY_POLICY
    assert "frame-ancestors 'none'" in CONTENT_SECURITY_POLICY
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY


def test_a_refusal_also_carries_the_headers(client: TestClient) -> None:
    res = client.get("/api/status", headers={"Host": "evil.example.com"})
    assert res.headers["x-frame-options"] == "DENY"


# ---------------------------------------------------- 10. schema behind lock
def test_the_openapi_schema_lives_under_the_gated_prefix(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/api/openapi.json").status_code == 200


def test_the_schema_is_refused_while_locked(client: TestClient) -> None:
    client.post(
        "/api/settings/pin",
        json={"new_pin": "864213"},
        headers={"Origin": "http://127.0.0.1:8647"},
    )
    client.cookies.clear()
    assert client.get("/api/openapi.json").status_code == 401


def test_no_docs_or_redoc_ui_is_served(client: TestClient) -> None:
    """Swagger UI/ReDoc fetch JS/CSS from cdn.jsdelivr.net and a favicon from
    fastapi.tiangolo.com — invariant 9 forbids third-party scripts, so both
    are disabled (docs_url=None, redoc_url=None) and must 404, not 401."""
    assert client.get("/api/docs").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/api/docs/oauth2-redirect").status_code == 404


# --------------------------------------------------- 5. webhook URL masking
def test_a_webhook_url_is_never_returned_in_full() -> None:
    secret_path = "/services/T00000/B00000/XXXXsecretXXXX"
    masked = mask_url("https://hooks.example.com" + secret_path)
    assert secret_path not in masked
    assert masked.startswith("https://hooks.example.com/")
    assert masked.endswith("XXXX")


def test_a_bare_host_webhook_masks_the_whole_path() -> None:
    assert mask_url("https://hooks.example.com/ab") == "https://hooks.example.com/***"
    assert mask_url("not-a-url") == "***"


# ------------------------------------------- 7. Content-Disposition escaping
def test_a_device_name_cannot_inject_header_directives() -> None:
    header = content_disposition('evil"; filename="owned.sh\r\nX-Injected: 1')
    assert "\r" not in header and "\n" not in header
    assert header.count('"') == 2
    assert header.startswith('attachment; filename="')


def test_the_real_name_survives_in_the_rfc5987_field() -> None:
    header = content_disposition("Küche-2026-09-19.csv")
    assert "filename*=UTF-8''" in header
    assert "K%C3%BCche" in header


def test_slugify_never_returns_an_empty_name() -> None:
    assert slugify_filename("///") == "export"
    assert slugify_filename("a" * 400) == "a" * 100


def test_an_export_download_header_is_well_formed(client: TestClient) -> None:
    res = client.get("/api/export?fmt=csv")
    assert res.status_code == 200
    header = res.headers["content-disposition"]
    assert header.startswith('attachment; filename="findplus-')
    assert "filename*=UTF-8''" in header


# ------------------------------------- 8. The composed page's sources (CF-1)
# `/` is composed from web/index.html + web/partials/*.html at startup, so the
# raw shell (with its `<!-- @partial: … -->` holes) and the pieces must not be
# reachable through /static. The guard compares a normalised path because APFS
# and NTFS are case-insensitive: before that, `/static/Index.html` served the
# shell the exact-match guard had just refused.
@pytest.mark.parametrize(
    "path",
    [
        "/static/index.html",
        "/static/Index.html",
        "/static/INDEX.HTML",
        "/static/partials/alerts.html",
        "/static/PARTIALS/alerts.html",
        "/static/Partials/Alerts.html",
    ],
)
def test_the_page_sources_are_not_served_from_static(client: TestClient, path: str) -> None:
    res = client.get(path)
    assert res.status_code == 404, f"{path} leaked the composed page's source"
    assert "@partial" not in res.text


def test_an_ordinary_static_asset_still_loads(client: TestClient) -> None:
    """The control: the guard must not turn /static into a black hole."""
    res = client.get("/static/style.css")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/css")


def test_the_composed_page_itself_still_has_every_partial(client: TestClient) -> None:
    """The other half of the guard: what /static refuses, "/" must still deliver."""
    import re

    from findplus.api import _static_dir
    from findplus.web_compose import partial_names

    res = client.get("/")
    assert res.status_code == 200
    assert "@partial" not in res.text
    static_dir = _static_dir()
    for name in partial_names(static_dir):
        source = (static_dir / "partials" / f"{name}.html").read_text()
        first_id = re.search(r'id="([^"]+)"', source)
        assert first_id, f"partial {name} has no id to anchor on"
        assert f'id="{first_id.group(1)}"' in res.text, f"partial {name} is missing from /"


def test_no_dotted_path_is_served_from_static(client: TestClient) -> None:
    """E1 security round 3 F4: /static served the whole static root.

    In the dev/monorepo tree that root IS the repo's web/ directory, so
    `GET /static/.claude/CLAUDE.md` returned 200 with the repo's own
    instruction file, unauthenticated, on 8647. The guard was an
    allow-everything-but-two list over a directory nobody curates file by file.
    """
    for path in (
        "/static/.claude/CLAUDE.md",
        "/static/.claude/AGENTS.md",
        "/static/.gitignore",
        "/static/app/../.claude/CLAUDE.md",
    ):
        res = client.get(path)
        assert res.status_code == 404, f"{path} -> {res.status_code}"
        assert "findplus-web-pac" not in res.text

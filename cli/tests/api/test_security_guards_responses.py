"""Regression tests for the blind security review of the local API, part 2.

Split from test_security_guards.py (E13 stage 2, size cap). Covered here:
response security headers, the OpenAPI schema now living behind the app
lock, webhook-URL masking, Content-Disposition escaping, and the composed
page's sources not being reachable through /static (CF-1).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from findplus.api.downloads import content_disposition, slugify_filename
from findplus.api.middleware import CONTENT_SECURITY_POLICY
from findplus.api.routes_alerts_channels import mask_url
from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from findplus.state import track_devices
from tests.conftest import make_observation


@pytest.fixture
def client(tmp_db):
    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2")
        track_devices(session, ["TAG-001"], exclusive=True)
        ingest_observations(session, [make_observation(minutes=0)])
    # Closeout C-M1: bind explicitly to 8647 -- this file's Host/Origin
    # parametrizations assert against that literal port.
    return TestClient(create_app(bound_host="127.0.0.1", bound_port=8647))


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
        source = (static_dir / "partials" / f"{name}.html").read_text(encoding="utf-8")
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

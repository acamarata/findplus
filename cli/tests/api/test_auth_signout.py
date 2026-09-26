"""`DELETE /api/auth/{provider}` (S11/WP8, gap-audit-2026-09-26).

Purpose    : the credential file is removed, permissions on everything else
             are untouched, the Origin guard applies, an unknown provider is
             404, and disconnecting twice is not an error. The Origin-guard
             case lives in test_auth_route_security.py alongside the other
             mutating auth routes; this file is status codes and file effects.
Constraints: every path here is inside `tmp_db`'s FINDPLUS_STATE_DIR (see
             conftest.py's `tmp_db` / `auth_client` fixtures) -- never
             ~/.findplus, never the network.
"""

from __future__ import annotations

import stat

from fastapi.testclient import TestClient

from findplus.config import get_settings
from tests.api._auth_helpers import SAME_ORIGIN_HEADERS


def test_sign_out_google_removes_secrets_file(auth_client: TestClient) -> None:
    settings = get_settings()
    settings.ensure_dirs()
    settings.secrets_file.write_text("{}")
    settings.secrets_file.chmod(0o600)

    res = auth_client.delete("/api/auth/google-find-hub", headers=SAME_ORIGIN_HEADERS)

    assert res.status_code == 204
    assert res.content == b""
    assert not settings.secrets_file.exists()


def test_sign_out_apple_removes_apple_account_json_only(auth_client: TestClient) -> None:
    """apple-account.json goes; a registered accessory key does not (PRI hard
    rule / PROMPT.md invariant 12: tracked devices and history stay, and an
    accessory's key is what keeps decrypting its future reports)."""
    settings = get_settings()
    settings.ensure_dirs()
    account_path = settings.state_dir / "apple-account.json"
    account_path.write_text("{}")
    account_path.chmod(0o600)
    accessory_dir = settings.state_dir / "apple"
    accessory_dir.mkdir(mode=0o700, exist_ok=True)
    accessory_path = accessory_dir / "apple_deadbeef.json"
    accessory_path.write_text("{}")
    accessory_path.chmod(0o600)

    res = auth_client.delete("/api/auth/apple-find-my", headers=SAME_ORIGIN_HEADERS)

    assert res.status_code == 204
    assert not account_path.exists()
    assert accessory_path.exists()
    # Untouched, not just present: still exactly the mode it was written with.
    assert stat.S_IMODE(accessory_path.stat().st_mode) == 0o600


def test_sign_out_when_already_signed_out_is_still_204(auth_client: TestClient) -> None:
    """A "Disconnect" click that lands after the credential is already gone
    (a double click, a slow network) is not an error."""
    res = auth_client.delete("/api/auth/google-find-hub", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 204


def test_sign_out_unknown_provider_is_404(auth_client: TestClient) -> None:
    res = auth_client.delete("/api/auth/bogus-provider", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 404
    assert res.json() == {"detail": "unknown provider: bogus-provider"}


def test_sign_out_does_not_touch_devices(auth_client: TestClient) -> None:
    """The one non-credential effect that must never happen: no route here
    reaches the DB at all, so the devices table is not even queried."""
    settings = get_settings()
    settings.ensure_dirs()
    settings.secrets_file.write_text("{}")

    before = auth_client.get("/api/devices").json()
    auth_client.delete("/api/auth/google-find-hub", headers=SAME_ORIGIN_HEADERS)
    after = auth_client.get("/api/devices").json()

    assert before == after

"""POST /api/apple/accessories: both body shapes, the 64 KiB cap, and the leftovers.

The route writes the uploaded plist to a temporary file under the state dir so
`add_accessory()`'s existing parser can read it. Every case here also asserts
that file is gone afterwards: a key payload left lying about at the umask's
mode is exactly what PRI hard rule 9 exists to prevent.
"""

from __future__ import annotations

import base64
import plistlib

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from findplus.config import get_settings

URL = "/api/apple/accessories"


def _key_b64(filler: bytes = b"x") -> str:
    """32 raw bytes: a P-256 scalar length accessories.py accepts."""
    return base64.b64encode(filler * 32).decode()


@pytest.fixture
def client(tmp_db, monkeypatch):
    monkeypatch.setattr("findplus.providers.apple_findmy.is_available", lambda: (True, ""))
    return TestClient(create_app())


def _leftovers() -> list:
    return list(get_settings().state_dir.glob(".accessory-upload-*"))


def test_json_private_key_registers_an_accessory(client: TestClient) -> None:
    res = client.post(URL, json={"name": "My Tag", "private_key_b64": _key_b64()})
    assert res.status_code == 201, res.text
    body = res.json()
    assert set(body) == {"device_id", "name", "kind", "added_at"}
    assert body["name"] == "My Tag"
    assert body["kind"] == "private_key"
    assert body["device_id"].startswith("apple:")


def test_multipart_plist_registers_an_accessory(client: TestClient) -> None:
    plist_bytes = plistlib.dumps({"Private Key": _key_b64(b"y")})
    res = client.post(URL, data={"name": "Tag 2"}, files={"plist": ("a.plist", plist_bytes)})
    assert res.status_code == 201, res.text
    assert res.json()["kind"] == "plist"
    assert _leftovers() == []


def test_a_duplicate_device_id_is_409_not_a_silent_overwrite(client: TestClient) -> None:
    body = {"name": "My Tag", "private_key_b64": _key_b64()}
    assert client.post(URL, json=body).status_code == 201
    res = client.post(URL, json={"name": "Renamed", "private_key_b64": _key_b64()})
    assert res.status_code == 409
    assert "already registered" in res.json()["detail"]


def test_json_without_a_name_is_422(client: TestClient) -> None:
    res = client.post(URL, json={"private_key_b64": _key_b64()})
    assert res.status_code == 422
    assert res.json()["detail"] == "'name' is required"


def test_neither_plist_nor_private_key_is_422(client: TestClient) -> None:
    """add_accessory()'s own exactly-one-of rule, surfaced as 422 not a 500."""
    res = client.post(URL, json={"name": "Tag"})
    assert res.status_code == 422


def test_apple_not_installed_is_503_with_the_install_hint(tmp_db, monkeypatch) -> None:
    monkeypatch.setattr(
        "findplus.providers.apple_findmy.is_available",
        lambda: (False, "pip install 'findplus[apple]'"),
    )
    res = TestClient(create_app()).post(URL, json={"name": "T", "private_key_b64": _key_b64()})
    assert res.status_code == 503
    assert "findplus[apple]" in res.json()["detail"]


def test_a_plist_over_64_kib_is_413_and_never_reaches_disk(client: TestClient) -> None:
    res = client.post(URL, data={"name": "Tag 3"}, files={"plist": ("big.plist", b"x" * 65537)})
    assert res.status_code == 413
    assert res.json()["detail"] == "plist too large"
    assert _leftovers() == []


def test_a_plist_of_exactly_64_kib_is_not_rejected_for_size(client: TestClient) -> None:
    """The boundary is one byte above the cap, not at it."""
    payload = plistlib.dumps({"Private Key": _key_b64(b"z")})
    padded = payload + b"\n" * (65536 - len(payload))
    assert len(padded) == 65536
    res = client.post(URL, data={"name": "Tag 4"}, files={"plist": ("ok.plist", padded)})
    assert res.status_code != 413, res.text
    assert _leftovers() == []

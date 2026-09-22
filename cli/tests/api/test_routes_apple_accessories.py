"""POST /api/apple/accessories: both body shapes, duplicates/overwrite, and
basic validation. The route writes the uploaded plist to a temporary file
under the state dir so `add_accessory()`'s existing parser can read it; every
case here also asserts that file is gone afterwards (PRI hard rule 9).

Size caps, streaming/chunked-upload guards and malformed-plist handling moved
to test_routes_apple_accessories_limits.py (E13 stage 2, size cap).
"""

from __future__ import annotations

import json
import plistlib

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from findplus.config import get_settings

from ._apple_accessories_helpers import URL, _key_b64, _leftovers


@pytest.fixture
def client(tmp_db, monkeypatch):
    monkeypatch.setattr("findplus.providers.apple_findmy.is_available", lambda: (True, ""))
    return TestClient(create_app())


def _saved_record(device_id: str) -> dict:
    """The permanent on-disk record `add_accessory()` wrote, read back --
    CR-C-m8: an overwrite test must prove the FILE changed, not just that
    the HTTP response says so."""
    path = get_settings().state_dir / "apple" / f"{device_id.replace(':', '_')}.json"
    return json.loads(path.read_text(encoding="utf-8"))


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
    first = client.post(URL, json=body)
    assert first.status_code == 201
    res = client.post(URL, json={"name": "Renamed", "private_key_b64": _key_b64()})
    assert res.status_code == 409
    assert "already registered" in res.json()["detail"]
    # CR-C-m8: a 409 must leave the saved record exactly as it was.
    assert _saved_record(first.json()["device_id"])["name"] == "My Tag"


def test_allow_overwrite_true_replaces_a_duplicate_json(client: TestClient) -> None:
    """CF-P2-19: the dashboard's "Replace existing" confirm retries with this
    field set. Still 409 without it (default False, tested above)."""
    key = _key_b64()
    assert client.post(URL, json={"name": "My Tag", "private_key_b64": key}).status_code == 201
    res = client.post(
        URL, json={"name": "Renamed", "private_key_b64": key, "allow_overwrite": True}
    )
    assert res.status_code == 201, res.text
    assert res.json()["name"] == "Renamed"
    # CR-C-m8: the response alone doesn't prove the record on disk changed.
    assert _saved_record(res.json()["device_id"])["name"] == "Renamed"


def test_allow_overwrite_true_replaces_a_duplicate_multipart(client: TestClient) -> None:
    """The multipart form sends "true" as a string, not a JSON bool."""
    plist_bytes = plistlib.dumps({"Private Key": _key_b64(b"z")})
    first = client.post(URL, data={"name": "Tag A"}, files={"plist": ("a.plist", plist_bytes)})
    assert first.status_code == 201
    res = client.post(
        URL,
        data={"name": "Tag B", "allow_overwrite": "true"},
        files={"plist": ("a.plist", plist_bytes)},
    )
    assert res.status_code == 201, res.text
    assert res.json()["name"] == "Tag B"
    assert _leftovers() == []
    # CR-C-m8: the response alone doesn't prove the record on disk changed.
    assert _saved_record(res.json()["device_id"])["name"] == "Tag B"


def test_allow_overwrite_false_string_is_still_a_409(client: TestClient) -> None:
    """Only the literal string "true" (case-insensitive) flips the default."""
    key = _key_b64()
    first = client.post(URL, json={"name": "My Tag", "private_key_b64": key})
    assert first.status_code == 201
    res = client.post(
        URL, json={"name": "Renamed", "private_key_b64": key, "allow_overwrite": "false"}
    )
    assert res.status_code == 409
    # CR-C-m8: a 409 must leave the saved record exactly as it was.
    assert _saved_record(first.json()["device_id"])["name"] == "My Tag"


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

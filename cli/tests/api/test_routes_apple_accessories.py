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


def test_allow_overwrite_false_string_is_still_a_409(client: TestClient) -> None:
    """Only the literal string "true" (case-insensitive) flips the default."""
    key = _key_b64()
    assert client.post(URL, json={"name": "My Tag", "private_key_b64": key}).status_code == 201
    res = client.post(
        URL, json={"name": "Renamed", "private_key_b64": key, "allow_overwrite": "false"}
    )
    assert res.status_code == 409


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


def test_an_oversized_content_length_is_rejected_before_the_body_is_parsed(
    client: TestClient, monkeypatch
) -> None:
    """E6-CRC-F6: the 413 must come from Content-Length, never from `request.form()`.

    Checking `upload.size` only after `await request.form()` bounds what gets
    written to disk but not what Starlette buffers while parsing. Patching
    `Request.form` to fail proves the guard rejects on the header alone.
    """
    from starlette.requests import Request

    def _form_must_not_be_called(self, *a, **k):
        raise AssertionError(
            "request.form() was awaited; the Content-Length guard did not short-circuit"
        )

    monkeypatch.setattr(Request, "form", _form_must_not_be_called)
    res = client.post(URL, data={"name": "Tag 5"}, files={"plist": ("huge.plist", b"x" * 200_000)})
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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"content": b"not json", "headers": {"content-type": "application/json"}},
        {"json": [1, 2, 3]},
        {"json": "a string"},
    ],
)
def test_an_unparseable_or_non_object_json_body_is_422_not_500(client: TestClient, kwargs) -> None:
    """CR-C-E6 F4: `await request.json()` raised JSONDecodeError and `.get()` on a
    list raised AttributeError, both uncaught — a malformed body was a 500."""
    res = client.post(URL, **kwargs)
    assert res.status_code == 422, res.text
    assert _leftovers() == []


@pytest.mark.posix_only
def test_the_uploaded_plist_is_0600_while_it_exists(client: TestClient, monkeypatch) -> None:
    """CR-C-E6 F3: the courier file holds raw key material and was created at the
    umask's mode (0644) before add_accessory() ever saw it. PRI hard rule 9."""
    import os
    import stat

    import findplus.api.routes_auth as routes_auth

    seen: dict[str, int] = {}

    def spy(name, settings, *, plist_path=None, private_key_b64=None, allow_overwrite=True):
        seen["mode"] = stat.S_IMODE(os.stat(plist_path).st_mode)
        return {"device_id": "aa", "name": name, "kind": "plist", "added_at": "t"}

    monkeypatch.setattr(routes_auth, "add_accessory", spy)
    res = client.post(URL, data={"name": "Tag 5"}, files={"plist": ("k.plist", b"xx")})
    assert res.status_code == 201, res.text
    assert seen["mode"] == 0o600
    assert _leftovers() == []

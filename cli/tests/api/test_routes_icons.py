"""POST/GET/DELETE /api/icons/custom: PNG validation, dedup, serving, delete-in-use.

Mirrors test_routes_apple_accessories.py's shape: every rejection case also
asserts nothing was written to `icons_dir`, since a courier file left behind
at the umask's mode is exactly what PRI hard rule 9 exists to prevent.
"""

from __future__ import annotations

import struct
import zlib
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from findplus.config import get_settings
from findplus.db.models import Group
from findplus.db.session import session_scope
from findplus.ingest import upsert_device

URL = "/api/icons/custom"


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data))
    )


def _make_png(width: int, height: int) -> bytes:
    """A real, valid grayscale PNG at the given dimensions."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00" * width for _ in range(height))
    idat = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _make_apng(size: int = 32) -> bytes:
    """A structurally valid PNG whose `acTL` chunk marks it animated."""
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)
    actl = struct.pack(">II", 1, 0)  # num_frames=1, num_plays=0 (loop forever)
    raw = b"".join(b"\x00" + b"\x00" * size for _ in range(size))
    idat = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"acTL", actl)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _icons_on_disk() -> list:
    return list(get_settings().icons_dir.glob("*.png"))


@pytest.fixture
def client(tmp_db):
    return TestClient(create_app())


def test_upload_valid_png_returns_a_content_addressed_id(client: TestClient) -> None:
    res = client.post(URL, files={"file": ("icon.png", _make_png(32, 32), "image/png")})
    assert res.status_code == 201, res.text
    icon_id = res.json()["id"]
    assert icon_id.startswith("custom:")
    assert len(icon_id.split(":", 1)[1]) == 16
    assert all(c in "0123456789abcdef" for c in icon_id.split(":", 1)[1])
    assert len(_icons_on_disk()) == 1


def test_uploaded_icon_is_served_with_the_pinned_headers(client: TestClient) -> None:
    png_bytes = _make_png(24, 24)
    icon_id = client.post(URL, files={"file": ("i.png", png_bytes, "image/png")}).json()["id"]
    short = icon_id.split(":", 1)[1]
    res = client.get(f"{URL}/{short}.png")
    assert res.status_code == 200
    assert res.content == png_bytes
    assert res.headers["content-type"] == "image/png"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["cache-control"] == "private, max-age=86400"


def test_list_returns_every_uploaded_id(client: TestClient) -> None:
    a = client.post(URL, files={"file": ("a.png", _make_png(20, 20), "image/png")}).json()["id"]
    b = client.post(URL, files={"file": ("b.png", _make_png(40, 40), "image/png")}).json()["id"]
    res = client.get(URL)
    assert res.status_code == 200
    assert sorted(res.json()) == sorted([a, b])


def test_duplicate_bytes_dedupe_to_one_file(client: TestClient) -> None:
    png_bytes = _make_png(16, 16)
    first = client.post(URL, files={"file": ("a.png", png_bytes, "image/png")}).json()["id"]
    second = client.post(URL, files={"file": ("b.png", png_bytes, "image/png")}).json()["id"]
    assert first == second
    assert len(_icons_on_disk()) == 1


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("icon.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
        ("icon.jpg", b"\xff\xd8\xff\xe0" + b"x" * 40),
        ("icon.gif", b"GIF89a" + b"x" * 40),
        ("polyglot.png", b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dXXXX" + b"\x00" * 13),
    ],
)
def test_non_png_uploads_are_415_and_never_reach_disk(
    client: TestClient, name: str, content: bytes
) -> None:
    res = client.post(URL, files={"file": (name, content, "application/octet-stream")})
    assert res.status_code == 415, res.text
    assert res.json()["detail"] == "file must be a PNG image"
    assert _icons_on_disk() == []


@pytest.mark.parametrize("dims", [(8, 8), (600, 600), (1024, 16)])
def test_bad_dimensions_are_422(client: TestClient, dims: tuple) -> None:
    res = client.post(URL, files={"file": ("i.png", _make_png(*dims), "image/png")})
    assert res.status_code == 422, res.text
    assert _icons_on_disk() == []


def test_dimensions_just_outside_the_ten_percent_skew_are_422(client: TestClient) -> None:
    # 100x89: skew = 11/100 = 11% > 10%.
    res = client.post(URL, files={"file": ("i.png", _make_png(100, 89), "image/png")})
    assert res.status_code == 422
    assert _icons_on_disk() == []


def test_dimensions_within_the_ten_percent_skew_are_accepted(client: TestClient) -> None:
    # 100x91: skew = 9/100 = 9% <= 10%.
    res = client.post(URL, files={"file": ("i.png", _make_png(100, 91), "image/png")})
    assert res.status_code == 201, res.text


def test_an_oversized_upload_is_413_and_never_reaches_disk(client: TestClient) -> None:
    # Size is checked before the PNG is parsed, so this need not decode as one.
    huge = b"x" * 70_000
    res = client.post(URL, files={"file": ("i.png", huge, "image/png")})
    assert res.status_code == 413
    assert res.json()["detail"] == "icon too large"
    assert _icons_on_disk() == []


def test_an_animated_png_is_415_and_never_reaches_disk(client: TestClient) -> None:
    """N3 (review, 2026-09-22): an `acTL` chunk marks a PNG animated; a
    structurally valid IHDR alone is not enough to accept it."""
    res = client.post(URL, files={"file": ("i.png", _make_apng(), "image/png")})
    assert res.status_code == 415, res.text
    assert res.json()["detail"] == "animated PNG is not supported"
    assert _icons_on_disk() == []


def test_trailing_bytes_after_iend_are_415_and_never_reach_disk(client: TestClient) -> None:
    """N3: bytes glued on after a structurally complete PNG (the shape a
    validated-then-appended payload would take) must not be silently kept."""
    padded = _make_png(20, 20) + b"extra-bytes-after-iend"
    res = client.post(URL, files={"file": ("i.png", padded, "image/png")})
    assert res.status_code == 415, res.text
    assert res.json()["detail"] == "file has trailing data after IEND"
    assert _icons_on_disk() == []


def test_an_oversized_content_length_is_rejected_before_the_body_is_parsed(
    client: TestClient, monkeypatch
) -> None:
    """The 413 must come from Content-Length, never from `request.form()`."""
    from starlette.requests import Request

    def _form_must_not_be_called(self, *a, **k):
        raise AssertionError("request.form() was awaited; the Content-Length guard skipped")

    monkeypatch.setattr(Request, "form", _form_must_not_be_called)
    res = client.post(URL, files={"file": ("i.png", b"x" * 200_000, "image/png")})
    assert res.status_code == 413
    assert res.json()["detail"] == "icon too large"
    assert _icons_on_disk() == []


def test_get_unknown_icon_is_404(client: TestClient) -> None:
    res = client.get(f"{URL}/00000000ffffffff.png")
    assert res.status_code == 404


def test_delete_removes_the_file(client: TestClient) -> None:
    icon_id = client.post(URL, files={"file": ("i.png", _make_png(20, 20), "image/png")}).json()[
        "id"
    ]
    short = icon_id.split(":", 1)[1]
    res = client.delete(f"{URL}/{short}")
    assert res.status_code == 204
    assert _icons_on_disk() == []
    assert client.get(f"{URL}/{short}.png").status_code == 404


def test_delete_unknown_icon_is_404(client: TestClient) -> None:
    assert client.delete(f"{URL}/00000000ffffffff").status_code == 404


@pytest.mark.parametrize(
    "bad_id",
    [
        "..",
        "../../../etc/passwd",
        "0123456789ABCDEF",  # uppercase
        "0123456789abcde",  # 15 chars
        "0123456789abcdef0",  # 17 chars
        "0123456789abcdeg",  # non-hex char
        "..%2f..%2fetc%2fpasswd",
    ],
)
def test_get_rejects_a_malformed_icon_id_before_touching_the_filesystem(
    client: TestClient, bad_id: str
) -> None:
    """N2 (review, 2026-09-22): `_validate_icon_id` refuses anything that is
    not exactly 16 lowercase hex chars, by design -- before a Path is ever
    built from it, regardless of whether Starlette's own `{icon_id}`
    converter (which already excludes "/") would have caught a given case."""
    res = client.get(f"{URL}/{bad_id}.png")
    assert res.status_code == 404, res.text


@pytest.mark.parametrize(
    "bad_id",
    [
        "..",
        "../../../etc/passwd",
        "0123456789ABCDEF",
        "0123456789abcde",
        "0123456789abcdef0",
        "0123456789abcdeg",
        "..%2f..%2fetc%2fpasswd",
    ],
)
def test_delete_rejects_a_malformed_icon_id_before_touching_the_filesystem(
    client: TestClient, bad_id: str
) -> None:
    res = client.delete(f"{URL}/{bad_id}")
    # A bare ".." with no further suffix (DELETE has none; GET's path always
    # ends in ".png") gets collapsed by URL normalization before routing --
    # "/api/icons/custom/.." resolves to "/api/icons", an existing GET-only
    # route, so it never reaches this handler at all and answers 405 instead
    # of 404. Either way nothing here was read, deleted, or reached by path.
    assert res.status_code in (404, 405), res.text


def test_a_malformed_icon_id_never_reaches_a_real_uploaded_file(client: TestClient) -> None:
    """The regex check runs before any lookup, so a well-formed-looking but
    wrong-case id cannot be used to fetch or delete a real upload."""
    icon_id = client.post(URL, files={"file": ("i.png", _make_png(20, 20), "image/png")}).json()[
        "id"
    ]
    short = icon_id.split(":", 1)[1]
    assert client.get(f"{URL}/{short.upper()}.png").status_code == 404
    assert client.delete(f"{URL}/{short.upper()}").status_code == 404
    assert len(_icons_on_disk()) == 1


def test_delete_refuses_while_a_device_uses_the_icon(client: TestClient) -> None:
    with session_scope() as session:
        upsert_device(session, "dev1", "Tag1")
    icon_id = client.post(URL, files={"file": ("i.png", _make_png(20, 20), "image/png")}).json()[
        "id"
    ]
    short = icon_id.split(":", 1)[1]
    patched = client.patch("/api/devices/dev1", json={"icon": icon_id})
    assert patched.status_code == 200, patched.text
    res = client.delete(f"{URL}/{short}")
    assert res.status_code == 409
    assert _icons_on_disk() != []
    # Unassign, then the delete succeeds.
    client.patch("/api/devices/dev1", json={"icon": "letter"})
    assert client.delete(f"{URL}/{short}").status_code == 204


def test_delete_refuses_while_a_group_uses_the_icon(client: TestClient) -> None:
    icon_id = client.post(URL, files={"file": ("i.png", _make_png(20, 20), "image/png")}).json()[
        "id"
    ]
    short = icon_id.split(":", 1)[1]
    with session_scope() as session:
        session.add(Group(name="Family", icon=icon_id, created_at=datetime.now(UTC)))
    res = client.delete(f"{URL}/{short}")
    assert res.status_code == 409
    assert _icons_on_disk() != []


def test_labels_validate_icon_accepts_an_uploaded_custom_icon(client: TestClient) -> None:
    with session_scope() as session:
        upsert_device(session, "dev1", "Tag1")
    icon_id = client.post(URL, files={"file": ("i.png", _make_png(20, 20), "image/png")}).json()[
        "id"
    ]
    res = client.patch("/api/devices/dev1", json={"icon": icon_id})
    assert res.status_code == 200, res.text
    assert res.json()["icon"] == icon_id


def test_labels_validate_icon_rejects_an_unknown_custom_icon(client: TestClient) -> None:
    with session_scope() as session:
        upsert_device(session, "dev1", "Tag1")
    res = client.patch("/api/devices/dev1", json={"icon": "custom:0000000000000000"})
    assert res.status_code == 422
    assert "custom icon" in res.json()["detail"][0]["msg"]


@pytest.mark.posix_only
def test_the_uploaded_icon_is_0600_and_the_dir_is_0700(client: TestClient) -> None:
    import os
    import stat

    client.post(URL, files={"file": ("i.png", _make_png(20, 20), "image/png")})
    icons_dir = get_settings().icons_dir
    assert stat.S_IMODE(os.stat(icons_dir).st_mode) == 0o700
    (path,) = _icons_on_disk()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

"""POST/GET /api/icons/custom: PNG validation, dedup, serving, size caps.

Mirrors test_routes_apple_accessories.py's shape: every rejection case also
asserts nothing was written to `icons_dir`, since a courier file left behind
at the umask's mode is exactly what PRI hard rule 9 exists to prevent.

DELETE, malformed-id rejection, delete-in-use guards and the 0600/0700
permission check moved to test_routes_icons_delete.py (E13 stage 2, size cap).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app

from ._icons_helpers import URL, _icons_on_disk, _make_apng, _make_png


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

"""GET/DELETE /api/icons/custom/{id}: unknown/malformed ids, delete-in-use
guards, label validation, and the 0600/0700 permission check. Split from
test_routes_icons.py (E13 stage 2, size cap).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from findplus.db.models import Group
from findplus.db.session import session_scope
from findplus.ingest import upsert_device

from ._icons_helpers import URL, _icons_on_disk, _make_png

_BAD_ICON_IDS = [
    "..",
    "../../../etc/passwd",
    "0123456789ABCDEF",  # uppercase
    "0123456789abcde",  # 15 chars
    "0123456789abcdef0",  # 17 chars
    "0123456789abcdeg",  # non-hex char
    "..%2f..%2fetc%2fpasswd",
]


@pytest.fixture
def client(tmp_db):
    return TestClient(create_app())


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


@pytest.mark.parametrize("bad_id", _BAD_ICON_IDS)
def test_get_rejects_a_malformed_icon_id_before_touching_the_filesystem(
    client: TestClient, bad_id: str
) -> None:
    """N2 (review, 2026-09-22): `_validate_icon_id` refuses anything that is
    not exactly 16 lowercase hex chars, by design -- before a Path is ever
    built from it, regardless of whether Starlette's own `{icon_id}`
    converter (which already excludes "/") would have caught a given case."""
    res = client.get(f"{URL}/{bad_id}.png")
    assert res.status_code == 404, res.text


@pytest.mark.parametrize("bad_id", _BAD_ICON_IDS)
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

    from findplus.config import get_settings

    client.post(URL, files={"file": ("i.png", _make_png(20, 20), "image/png")})
    icons_dir = get_settings().icons_dir
    assert stat.S_IMODE(os.stat(icons_dir).st_mode) == 0o700
    (path,) = _icons_on_disk()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
